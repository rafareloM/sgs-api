"""Só o Caddy, pelo IP fixo, informa o IP do cliente à auditoria (spec 013, T4; R3.1, R3.3, R3.8).

Sobe `db-certs`, `db`, `api` e `proxy` do docker/compose.yml num projeto próprio
(`sgs-api-e2e-auditoria`), com portas e subnet de borda próprias (`tests/e2e/redes.py`), e
derruba só esse projeto, com os volumes dele, no fim. Três tentativas de escolher o IP gravado com
um `X-Forwarded-For` falso, cada uma identificada por um User-Agent próprio, e o IP efetivamente
gravado em `audit_log` (evento `auth.login_failed` de um usuário inexistente):

- A: cliente → Caddy (porta publicada). Vale o IP que o Caddy viu, não o falso.
- B: contêiner descartável só na rede `dados` → API direto. Vale o IP do contêiner.
- C: host → IP da API na rede `borda`, com origem no gateway da bridge. Vale o gateway.

Fica fora do `make check`; rodar à parte com `uv run pytest tests/e2e/test_auditoria_proxy.py -m
slow`.
"""

import json
import os
import shutil
import ssl
import subprocess
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest

from src.tools import crypto_keys, jwt_keys
from tests.e2e import segredos
from tests.e2e.redes import Borda, SubnetOcupadaError, borda_da_suite

pytestmark = pytest.mark.slow

RAIZ = Path(__file__).resolve().parents[2]
COMPOSE = RAIZ / "docker" / "compose.yml"
COMPOSE_TESTE = RAIZ / "docker" / "compose.test.yml"
PROJETO = "sgs-api-e2e-auditoria"
PORTA_HTTP = "18082"
PORTA_HTTPS = "18445"
# Lidos por tests/architecture/test_compose_configuracao.py: a API tem de aceitar esta configuração.
ARQUIVOS_COMPOSE = (COMPOSE, COMPOSE_TESTE)
AMBIENTE_COMPOSE = {"SGS_HTTP_PORT": PORTA_HTTP, "SGS_HTTPS_PORT": PORTA_HTTPS}
CHAVES_JWT = RAIZ / "secrets" / "jwt-keys.json"
CHAVES_DE_CIFRA = RAIZ / "secrets" / "crypto-keys.json"
DOCKER = shutil.which("docker")
CA_DO_CADDY = "/data/caddy/pki/authorities/local/root.crt"
FALSO = "6.6.6.6"
LOGIN = '{"username": "ninguem-e2e", "password": "x"}'

type Resultado = subprocess.CompletedProcess[str]

_BORDA: list[Borda] = []

# Roda dentro do contêiner vizinho (imagem da própria API, que tem Python): manda o login com XFF
# falso direto para a API pela rede `dados` e imprime o IP de origem que ele usou.
_VIZINHO = """
import socket, sys, urllib.request
pedido = urllib.request.Request(
    "http://api:8000/api/v1/auth/login", data=sys.argv[1].encode(), method="POST",
    headers={"Content-Type": "application/json", "X-Forwarded-For": sys.argv[2],
             "User-Agent": "e2e-vizinho"})
try:
    urllib.request.urlopen(pedido, timeout=10)
except urllib.error.HTTPError:
    pass
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.connect(("api", 8000))
print(s.getsockname()[0])
"""


def _docker(*args: str, check: bool = True, timeout: int = 120) -> Resultado:
    assert DOCKER is not None
    ambiente = os.environ | AMBIENTE_COMPOSE | _BORDA[0].ambiente()
    # Comandos fixos deste arquivo, sem entrada externa.
    return subprocess.run(  # noqa: S603
        [DOCKER, *args],
        capture_output=True,
        text=True,
        check=check,
        timeout=timeout,
        cwd=RAIZ,
        env=ambiente,
    )


def _compose(*args: str, check: bool = True, timeout: int = 120) -> Resultado:
    arquivos = [*(a for f in ARQUIVOS_COMPOSE for a in ("-f", str(f))), "-p", PROJETO]
    return _docker("compose", *arquivos, *args, check=check, timeout=timeout)


def _ip_gravado(user_agent: str) -> str:
    # O User-Agent é uma das constantes `e2e-*` deste arquivo, nunca entrada externa.
    assert user_agent.replace("-", "").isalnum()
    sql = f"SELECT ip FROM audit_log WHERE action = 'auth.login_failed' AND user_agent = '{user_agent}' ORDER BY id DESC LIMIT 1"  # noqa: E501, S608
    saida = _compose("exec", "-T", "db", "psql", "-U", "sgs", "-d", "sgs", "-AtX", "-c", sql)
    return saida.stdout.strip()


def _login(url: str, user_agent: str, contexto: ssl.SSLContext | None = None) -> int:
    pedido = urllib.request.Request(  # noqa: S310 - URL fixa do ambiente do teste
        url,
        data=LOGIN.encode(),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Forwarded-For": FALSO,
            "X-Real-IP": FALSO,
            "User-Agent": user_agent,
        },
    )
    try:
        with urllib.request.urlopen(pedido, context=contexto, timeout=10) as resposta:  # noqa: S310
            return int(resposta.status)
    except urllib.error.HTTPError as erro:
        return erro.code


@pytest.fixture(scope="module")
def contexto_tls(tmp_path_factory: pytest.TempPathFactory) -> Iterator[ssl.SSLContext]:
    if DOCKER is None:
        pytest.skip("Docker não encontrado")
    # Antes de subir qualquer coisa: a subnet da suíte não pode sobrepor rede existente.
    try:
        _BORDA[:] = [borda_da_suite("AUDITORIA", DOCKER, projeto=PROJETO)]
    except SubnetOcupadaError as erro:
        pytest.skip(str(erro))
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
        # Só o projeto descartável deste arquivo, pelo nome, com os volumes dele.
        _compose("down", "-v", "--remove-orphans", check=False, timeout=300)
        if criou_chave:
            CHAVES_JWT.unlink(missing_ok=True)
        if criou_cifra:
            CHAVES_DE_CIFRA.unlink(missing_ok=True)
        segredos.apagar(segredos_da_005)
        if criou_pasta:
            CHAVES_JWT.parent.rmdir()


def _ip_do_servico_na_rede(servico: str, rede: str) -> str:
    [conteiner] = _compose("ps", "-q", servico).stdout.split()
    redes = json.loads(
        _docker("inspect", "--format", "{{json .NetworkSettings.Networks}}", conteiner).stdout
    )
    return str(redes[f"{PROJETO}_{rede}"]["IPAddress"])


def test_xff_do_cliente_nao_vira_ip_registrado(contexto_tls: ssl.SSLContext) -> None:
    """013/R3.3 (cenário A): o Caddy descarta o XFF do cliente e a API grava o IP que o Caddy
    viu, que não é o falso nem o do próprio Caddy."""
    status = _login(
        f"https://localhost:{PORTA_HTTPS}/api/v1/auth/login", "e2e-cenario-a", contexto_tls
    )

    assert status == 401
    gravado = _ip_gravado("e2e-cenario-a")
    assert gravado
    assert gravado not in {FALSO, _BORDA[0].proxy_ip}


def test_vizinho_na_rede_dados_nao_forja_ip(contexto_tls: ssl.SSLContext) -> None:
    """013/R3.8 (cenário B): um contêiner que só está na rede `dados` fala direto com a API; o
    XFF dele não vale, e o IP gravado é o dele."""
    imagem = _compose("images", "-q", "api").stdout.split()[0]

    vizinho = _docker(
        "run",
        "--rm",
        "--name",
        f"{PROJETO}-vizinho",
        "--network",
        f"{PROJETO}_dados",
        "--entrypoint",
        "python",
        imagem,
        "-c",
        _VIZINHO,
        LOGIN,
        FALSO,
    )

    ip_do_vizinho = vizinho.stdout.strip()
    assert ip_do_vizinho
    assert _ip_gravado("e2e-vizinho") == ip_do_vizinho


def test_gateway_da_borda_nao_e_confiavel(contexto_tls: ssl.SSLContext) -> None:
    """013/R3.8 (cenário C): o host alcança a API pelo IP dela na `borda`, com origem no gateway
    da bridge, que está na subnet mas não é o proxy; o XFF não vale."""
    ip_da_api = _ip_do_servico_na_rede("api", "borda")
    try:
        status = _login(f"http://{ip_da_api}:8000/api/v1/auth/login", "e2e-cenario-c")
    except (urllib.error.URLError, TimeoutError, OSError) as erro:
        pytest.skip(f"o host não alcança a rede da bridge ({erro}); cenário C não reproduzível")

    assert status == 401
    gravado = _ip_gravado("e2e-cenario-c")
    assert gravado != FALSO
    assert gravado == _BORDA[0].gateway_ip
