"""Entrega do front pelo Caddy no mesmo domínio da API (spec 012, T1: R1.1 e R15.2).

Sobe `db-certs`, `db`, `api` e `proxy` do docker/compose.yml num projeto próprio, com as portas
do proxy trocadas (80 e 443 podem estar ocupadas na máquina), e derruba tudo, com os volumes, no
fim. O certificado é conferido contra a CA interna do próprio Caddy, sem desligar a verificação.
Fica fora do `make check`; rodar à parte com
`uv run pytest tests/e2e/test_frontend_entrega.py -m slow`.
"""

import json
import os
import shutil
import ssl
import subprocess
import urllib.error
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from src.tools import crypto_keys, jwt_keys
from tests.e2e import segredos
from tests.e2e.redes import Borda, SubnetOcupadaError, borda_da_suite

pytestmark = pytest.mark.slow

RAIZ = Path(__file__).resolve().parents[2]
COMPOSE = RAIZ / "docker" / "compose.yml"
COMPOSE_TESTE = RAIZ / "docker" / "compose.test.yml"
PROJETO = "sgs-api-e2e-front"
PORTA_HTTPS = "18443"
PORTA_HTTP = "18080"
BASE = f"https://localhost:{PORTA_HTTPS}"
# Lidos por tests/architecture/test_compose_configuracao.py: a API tem de aceitar esta configuração.
ARQUIVOS_COMPOSE = (COMPOSE, COMPOSE_TESTE)
AMBIENTE_COMPOSE = {"SGS_HTTP_PORT": PORTA_HTTP, "SGS_HTTPS_PORT": PORTA_HTTPS}
CHAVES_JWT = RAIZ / "secrets" / "jwt-keys.json"
CHAVES_DE_CIFRA = RAIZ / "secrets" / "crypto-keys.json"
DOCKER = shutil.which("docker")
CA_DO_CADDY = "/data/caddy/pki/authorities/local/root.crt"

CSP_ESPERADA = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; "
    "base-uri 'none'; form-action 'self'"
)

type Resultado = subprocess.CompletedProcess[str]


@dataclass(frozen=True)
class Resposta:
    status: int
    cabecalhos: dict[str, str]
    corpo: str


_BORDA: list[Borda] = []
"""Subnet de borda da suíte (spec 013, T4), escolhida antes do `up`."""


def _compose(*args: str, check: bool = True, timeout: int = 120) -> Resultado:
    assert DOCKER is not None
    ambiente = os.environ | AMBIENTE_COMPOSE | _BORDA[0].ambiente()
    comando = [
        DOCKER,
        "compose",
        *(a for f in ARQUIVOS_COMPOSE for a in ("-f", str(f))),
        "-p",
        PROJETO,
    ]
    # Comandos fixos deste arquivo, sem entrada externa.
    return subprocess.run(  # noqa: S603
        [*comando, *args],
        capture_output=True,
        text=True,
        check=check,
        timeout=timeout,
        cwd=RAIZ,
        env=ambiente,
    )


@pytest.fixture(scope="module")
def contexto_tls(tmp_path_factory: pytest.TempPathFactory) -> Iterator[ssl.SSLContext]:
    if DOCKER is None:
        pytest.skip("Docker não encontrado")
    try:
        _BORDA[:] = [borda_da_suite("FRONT", DOCKER, projeto=PROJETO)]
    except SubnetOcupadaError as erro:
        pytest.skip(str(erro))
    # A API não sobe sem as chaves (spec 002); se elas não existem, o teste cria e apaga no fim.
    criou_pasta = not CHAVES_JWT.parent.exists()
    criou_chave = not CHAVES_JWT.exists()
    criou_cifra = not CHAVES_DE_CIFRA.exists()
    if criou_chave:
        CHAVES_JWT.parent.mkdir(exist_ok=True)
        jwt_keys.main(["--output", str(CHAVES_JWT)])
    if criou_cifra:
        CHAVES_DE_CIFRA.parent.mkdir(exist_ok=True)
        crypto_keys.main(["--output", str(CHAVES_DE_CIFRA)])
    segredos_da_005 = segredos.criar_faltando(segredos.DA_005)
    try:
        subida = _compose("up", "-d", "--build", "--wait", "proxy", check=False, timeout=900)
        if subida.returncode != 0:
            logs = _compose("logs", "--no-color", "--tail", "100", check=False)
            pytest.fail(f"o compose não subiu:\n{subida.stderr}\n{logs.stdout}")
        ca = tmp_path_factory.mktemp("caddy") / "root.crt"
        _compose("cp", f"proxy:{CA_DO_CADDY}", str(ca))
        yield ssl.create_default_context(cafile=str(ca))
    finally:
        _compose("down", "-v", "--remove-orphans", check=False, timeout=300)
        if criou_chave:
            CHAVES_JWT.unlink(missing_ok=True)
        if criou_cifra:
            CHAVES_DE_CIFRA.unlink(missing_ok=True)
        segredos.apagar(segredos_da_005)
        if criou_pasta:
            CHAVES_JWT.parent.rmdir()


def _get(contexto: ssl.SSLContext, caminho: str) -> Resposta:
    # URL fixa do proxy local do teste.
    pedido = urllib.request.Request(BASE + caminho)  # noqa: S310
    try:
        with urllib.request.urlopen(pedido, context=contexto, timeout=10) as resposta:  # noqa: S310
            return Resposta(resposta.status, dict(resposta.headers), resposta.read().decode())
    except urllib.error.HTTPError as erro:
        return Resposta(erro.code, dict(erro.headers), erro.read().decode())


def test_raiz_serve_o_html_do_front_com_csp(contexto_tls: ssl.SSLContext) -> None:
    """012/R1.1, R15.2"""
    resposta = _get(contexto_tls, "/")

    assert resposta.status == 200
    assert resposta.cabecalhos["Content-Type"].startswith("text/html")
    assert '<html lang="pt-BR">' in resposta.corpo
    assert resposta.cabecalhos["Content-Security-Policy"] == CSP_ESPERADA
    assert "unsafe-eval" not in resposta.cabecalhos["Content-Security-Policy"]
    assert resposta.cabecalhos["X-Content-Type-Options"] == "nosniff"
    assert resposta.cabecalhos["Referrer-Policy"] == "no-referrer"


def test_rota_do_front_desconhecida_volta_para_o_index(contexto_tls: ssl.SSLContext) -> None:
    """012/R1.1: o roteamento é do front; o Caddy entrega o index.html."""
    raiz = _get(contexto_tls, "/")
    resposta = _get(contexto_tls, "/unidades/qualquer-coisa")

    assert resposta.status == 200
    assert resposta.corpo == raiz.corpo


def test_api_sem_token_responde_401_da_propria_api(contexto_tls: ssl.SSLContext) -> None:
    """012/R1.1: /api/* vai para a API, que nega sem token (problem+json), e não para o front."""
    resposta = _get(contexto_tls, "/api/v1/me")

    assert resposta.status == 401
    assert resposta.cabecalhos["Content-Type"].startswith("application/problem+json")
    assert "Content-Security-Policy" not in resposta.cabecalhos


def test_rota_inexistente_da_api_nao_cai_no_index(contexto_tls: ssl.SSLContext) -> None:
    """012/R1.1: um 404 da API não pode virar o index.html do front."""
    resposta = _get(contexto_tls, "/api/v1/rota-que-nao-existe")

    assert resposta.status == 404
    assert "<html" not in resposta.corpo


def test_health_e_jwks_continuam_na_api(contexto_tls: ssl.SSLContext) -> None:
    """012/R1.1: /health/* e /.well-known/* continuam servidos pela API."""
    pronta = _get(contexto_tls, "/health/ready")
    jwks = _get(contexto_tls, "/.well-known/jwks.json")

    assert pronta.status == 200
    assert json.loads(pronta.corpo) == {"status": "ok"}
    assert jwks.status == 200
    assert json.loads(jwks.corpo)["keys"]
