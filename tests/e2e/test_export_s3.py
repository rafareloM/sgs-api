"""Exportação de relatórios ponta a ponta com o SeaweedFS do compose (spec 005, T8; R2.7, R2.8,
R6.1 a R6.3; design § Ambiente de demonstração).

Sobe `proxy`, `api`, `s3` e `s3-init` do docker/compose.yml num projeto próprio
(`sgs-api-e2e-s3`), com portas e subnet de borda próprias (`tests/e2e/redes.py`), e derruba só esse
projeto, com os volumes dele, no fim. Confere, como no roteiro `docs/operacao/demo-relatorios.md`:

- a primeira hora da T8, já no compose: o S3 só em HTTPS e o objeto gravado com `AES256` e o
  checksum SHA-256, lidos do próprio SeaweedFS pela rede `integracoes`;
- o pedido pela API, a geração em segundo plano e o envio, com a SSE e o checksum conferidos
  pela API (R2.8): sem isso o pedido não fica `concluido`;
- o download da URL pré-assinada pelo navegador do host (Playwright), em `s3.localhost`, pelo
  Caddy (R3.6, R6.2);
- o hash e a assinatura do arquivo baixado, conferidos só com a JWK pública (R5.4).

Fica fora do `make check`; rodar à parte com `uv run pytest tests/e2e/test_export_s3.py -m slow`.
"""

import base64
import hashlib
import json
import os
import secrets
import shutil
import ssl
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pyotp
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import Prehashed, encode_dss_signature
from playwright.sync_api import Error as ErroDoPlaywright
from playwright.sync_api import sync_playwright

from tests.e2e import segredos
from tests.e2e.redes import Borda, SubnetOcupadaError, borda_da_suite

pytestmark = pytest.mark.slow

RAIZ = Path(__file__).resolve().parents[2]
COMPOSE = RAIZ / "docker" / "compose.yml"
COMPOSE_TESTE = RAIZ / "docker" / "compose.test.yml"
PROJETO = "sgs-api-e2e-s3"
PORTA_HTTP = "18084"
PORTA_HTTPS = "18447"
PUBLICA = f"https://localhost:{PORTA_HTTPS}"
S3_PUBLICO = f"https://s3.localhost:{PORTA_HTTPS}"
# Lidos por tests/architecture/test_compose_configuracao.py: a API tem de aceitar esta configuração.
ARQUIVOS_COMPOSE = (COMPOSE, COMPOSE_TESTE)
AMBIENTE_COMPOSE = {
    "SGS_HTTP_PORT": PORTA_HTTP,
    "SGS_HTTPS_PORT": PORTA_HTTPS,
    "SGS_PUBLIC_URL": PUBLICA,
    "SGS_PUBLIC_KEYCLOAK_URL": f"https://keycloak.localhost:{PORTA_HTTPS}",
    "SGS_PUBLIC_S3_URL": S3_PUBLICO,
}


DOCKER = shutil.which("docker")
CA_DO_CADDY = "/data/caddy/pki/authorities/local/root.crt"
USUARIO = "gestor.e2e.s3"

type Resultado = subprocess.CompletedProcess[str]

_BORDA: list[Borda] = []

# Roda dentro do contêiner da API, com a configuração S3 do compose: lê do SeaweedFS, pela rede
# `integracoes`, o que ficou gravado (a primeira hora da T8, R2.8). Argumento: a chave do objeto.
_CABECALHO_DO_OBJETO = """
import json, os, sys, boto3
from botocore.config import Config
cliente = boto3.client(
    "s3", endpoint_url=os.environ["S3_ENDPOINT_URL"], region_name=os.environ["S3_REGION"],
    aws_access_key_id=os.environ["S3_ACCESS_KEY_ID"],
    aws_secret_access_key=os.environ["S3_SECRET_ACCESS_KEY"], verify=os.environ["S3_CA_FILE"],
    config=Config(s3={"addressing_style": "path"}, request_checksum_calculation="when_required",
                  response_checksum_validation="when_required"))
r = cliente.head_object(Bucket=os.environ["S3_BUCKET"], Key=sys.argv[1], ChecksumMode="ENABLED")
v = cliente.get_bucket_versioning(Bucket=os.environ["S3_BUCKET"])
print(json.dumps({"sse": r.get("ServerSideEncryption"), "checksum": r.get("ChecksumSHA256"),
                  "versao": r.get("VersionId"), "versionamento": v.get("Status")}))
"""
# O S3 em HTTP na mesma porta: o SeaweedFS só fala HTTPS ali (R2.7).
_HTTP_NO_S3 = """
import urllib.error, urllib.request
try:
    print(urllib.request.urlopen("http://s3:8333/", timeout=5).status)
except urllib.error.HTTPError as erro:
    print(erro.code, erro.read().decode(errors="replace")[:80])
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


def _na_api(script: str, *args: str) -> str:
    return _compose("exec", "-T", "api", "python", "-c", script, *args).stdout


@pytest.fixture(scope="module")
def ambiente(tmp_path_factory: pytest.TempPathFactory) -> Iterator[dict[str, Any]]:
    if DOCKER is None:
        pytest.skip("Docker não encontrado")
    try:
        _BORDA[:] = [borda_da_suite("S3", DOCKER, projeto=PROJETO)]
    except SubnetOcupadaError as erro:
        pytest.skip(str(erro))
    criados = segredos.criar_faltando()
    senha = secrets.token_urlsafe(16)
    try:
        subida = _compose(
            "up", "-d", "--build", "--wait", "proxy", "s3", "s3-init", check=False, timeout=900
        )
        if subida.returncode != 0:
            logs = _compose("logs", "--no-color", "--tail", "100", check=False)
            pytest.fail(f"o compose não subiu:\n{subida.stderr}\n{logs.stdout}")
        _esperar_o_s3_init()
        _compose(
            "exec",
            "-T",
            "-e",
            f"SGS_SENHA_INICIAL={senha}",
            "api",
            "sgs-admin",
            "create-user",
            "--username",
            USUARIO,
            "--nome",
            "Gestor de dados (e2e)",
            "--papel",
            "GESTOR_DADOS",
        )
        ca = tmp_path_factory.mktemp("caddy") / "root.crt"
        _compose("cp", f"proxy:{CA_DO_CADDY}", str(ca))
        yield {"ca": ca, "senha": senha}
    finally:
        # Só o projeto descartável deste arquivo, pelo nome, com os volumes dele.
        _compose("down", "-v", "--remove-orphans", check=False, timeout=300)
        segredos.apagar(criados)


def _esperar_o_s3_init() -> None:
    for _ in range(60):
        estado = json.loads(_compose("ps", "-a", "--format", "json", "s3-init").stdout or "{}")
        if estado.get("State") == "exited":
            assert estado.get("ExitCode") == 0, _compose("logs", "s3-init", check=False).stdout
            return
        time.sleep(2)
    pytest.fail("o s3-init não terminou")


@pytest.fixture(scope="module")
def api(ambiente: dict[str, Any]) -> Iterator[httpx.Client]:
    """A API pelo Caddy, confiando só na CA dele, com o access token do gestor de dados."""
    contexto = ssl.create_default_context(cafile=str(ambiente["ca"]))
    with httpx.Client(base_url=PUBLICA, verify=contexto, timeout=30) as cliente:
        for _ in range(10):
            if cliente.get("/health/ready").status_code == 200:
                break
            time.sleep(2)
        desafio = cliente.post(
            "/api/v1/auth/login", json={"username": USUARIO, "password": ambiente["senha"]}
        ).json()["mfa_token"]
        uri = cliente.post("/api/v1/auth/mfa/enroll", json={"mfa_token": desafio}).json()[
            "otpauth_uri"
        ]
        segredo = parse_qs(urlsplit(uri).query)["secret"][0]
        confirmado = cliente.post(
            "/api/v1/auth/mfa/confirm",
            json={"mfa_token": desafio, "code": pyotp.TOTP(segredo).now()},
        )
        assert confirmado.status_code == 200, confirmado.text
        cliente.headers["Authorization"] = f"Bearer {confirmado.json()['access_token']}"
        yield cliente


def _pedir_e_esperar(api: httpx.Client, corpo: dict[str, Any]) -> dict[str, Any]:
    pedido = api.post("/api/v1/relatorios", json=corpo)
    assert pedido.status_code == 202, pedido.text
    for _ in range(60):
        relatorio: dict[str, Any] = api.get(f"/api/v1/relatorios/{pedido.json()['id']}").json()
        if relatorio["status"] in ("concluido", "falhou"):
            return relatorio
        time.sleep(1)
    pytest.fail("o relatório não terminou em 60 s")


def _baixar_pelo_navegador(url: str, destino: Path) -> Path:
    """Abre a URL num Chromium do host, como quem pede o download: `s3.localhost` vai à própria
    máquina, e o Caddy leva ao SeaweedFS com o `Host` assinado."""
    with sync_playwright() as p:
        try:
            navegador = p.chromium.launch()
        except ErroDoPlaywright:
            chromium = shutil.which("chromium")
            if chromium is None:
                pytest.skip("sem Chromium para o Playwright (`uv run playwright install chromium`)")
            navegador = p.chromium.launch(executable_path=chromium)
        try:
            # CA interna do Caddy só de teste; a conferência do certificado em si é da 012/T1.
            contexto = navegador.new_context(ignore_https_errors=True, accept_downloads=True)
            pagina = contexto.new_page()
            abortada = ""
            with pagina.expect_download() as baixando:
                try:
                    pagina.goto(url)
                except ErroDoPlaywright as erro:  # o Chromium aborta a navegação do anexo
                    abortada = str(erro)
            assert not abortada or "Download is starting" in abortada, abortada
            download = baixando.value
            caminho = destino / download.suggested_filename
            download.save_as(caminho)
            return caminho
        finally:
            navegador.close()


def _confere_assinatura(jwks: dict[str, Any], kid: str, sha256: bytes, valor: str) -> None:
    """Só com a JWK publicada (R5.4), como em docs/operacao/verificar-relatorio.md."""
    [jwk] = [chave for chave in jwks["keys"] if chave["kid"] == kid]

    def b64url(campo: str) -> bytes:
        return base64.urlsafe_b64decode(campo + "=" * (-len(campo) % 4))

    publica = ec.EllipticCurvePublicNumbers(
        int.from_bytes(b64url(jwk["x"]), "big"),
        int.from_bytes(b64url(jwk["y"]), "big"),
        ec.SECP256R1(),
    ).public_key()
    assinatura = b64url(valor)
    der = encode_dss_signature(
        int.from_bytes(assinatura[:32], "big"), int.from_bytes(assinatura[32:], "big")
    )
    publica.verify(der, sha256, ec.ECDSA(Prehashed(hashes.SHA256())))


def test_s3_do_compose_so_fala_https(ambiente: dict[str, Any]) -> None:
    """005/R2.7, R6.1 (primeira hora da T8: o TLS da T10, já no compose)"""
    saida = _na_api(_HTTP_NO_S3)

    assert saida.startswith("400"), saida


@pytest.mark.parametrize(
    ("corpo", "extensao"),
    [
        pytest.param({"tipo": "inventario_unidades", "formato": "csv"}, "csv", id="inventario-csv"),
        pytest.param(
            {
                "tipo": "trilha_auditoria",
                "formato": "xlsx",
                "filtros": {"de": "2026-01-01T00:00:00-03:00", "ate": "2026-12-31T00:00:00-03:00"},
            },
            "xlsx",
            id="trilha-xlsx",
        ),
    ],
)
def test_pedido_envio_e_download_pelo_navegador_com_hash_e_assinatura(
    api: httpx.Client, tmp_path: Path, corpo: dict[str, Any], extensao: str
) -> None:
    """005/R2.8, R3.2, R3.6, R6.2, R6.3, R5.1 (envio com SSE e checksum conferidos; download pelo
    navegador em s3.localhost; hash e assinatura conferidos com a JWK pública)"""
    relatorio = _pedir_e_esperar(api, corpo)
    assert relatorio["status"] == "concluido", relatorio
    integridade = relatorio["integridade"]

    download = api.get(f"/api/v1/relatorios/{relatorio['id']}/download")
    assert download.status_code == 200, download.text
    assert download.headers["cache-control"] == "no-store"
    url = download.json()["url"]
    partes = urlsplit(url)
    assert (partes.scheme, partes.netloc) == ("https", f"s3.localhost:{PORTA_HTTPS}")
    assert parse_qs(partes.query)["X-Amz-Expires"] == ["300"]

    arquivo = _baixar_pelo_navegador(url, tmp_path)
    conteudo = arquivo.read_bytes()
    sha256 = hashlib.sha256(conteudo).digest()
    assert arquivo.name.startswith(f"sgs-{corpo['tipo']}-")
    assert arquivo.suffix == f".{extensao}"
    assert sha256.hex() == integridade["sha256"]
    jwks = api.get("/.well-known/relatorios-jwks.json").json()
    _confere_assinatura(jwks, integridade["kid"], sha256, integridade["assinatura"])

    chave = f"reports/{relatorio['criado_em'][:4]}/{relatorio['criado_em'][5:7]}/{corpo['tipo']}/"
    gravado = json.loads(_na_api(_CABECALHO_DO_OBJETO, f"{chave}{relatorio['id']}.{extensao}"))
    assert gravado["sse"] == "AES256"
    assert gravado["checksum"] == base64.b64encode(sha256).decode()
    assert gravado["versao"]
    assert gravado["versionamento"] == "Enabled"
