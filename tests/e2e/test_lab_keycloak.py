"""Keycloak de laboratório atrás do Caddy (spec 004, T8; R5.2; design § Ambiente).

Sobe `proxy` e `keycloak` do docker/compose.yml (com `api`, `db` e os certificados) num projeto
próprio (`sgs-api-e2e-keycloak`), com portas e subnet de borda próprias (`tests/e2e/redes.py`), e
derruba só esse projeto, com os volumes dele, no fim. Confere:

- o mesmo `issuer` pela descoberta pública (navegador → Caddy → Keycloak) e pela interna (API →
  `https://keycloak:8443`, com a CA de laboratório): é o risco do design § Riscos;
- o Keycloak só com HTTPS na rede;
- o cliente `sgs-api`: PKCE S256 exigido, só a redirect URI exata, sem senha direta;
- a claim `groups` no `id_token` de um usuário de exemplo, com o código trocado pela API;
- o `servicos-certs`: cada chave com o dono do seu contêiner e sem a chave da CA;
- a API pronta sem o Keycloak.

O navegador é simulado pelo httpx: `keycloak.localhost` vai para 127.0.0.1, com o nome no `Host` e
no SNI, sem depender de o host resolver `*.localhost`. Fica fora do `make check`; rodar à parte com
`uv run pytest tests/e2e/test_lab_keycloak.py -m slow`.
"""

import base64
import hashlib
import html
import json
import os
import re
import secrets
import shutil
import ssl
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from src.tools import crypto_keys, jwt_keys
from tests.e2e import segredos
from tests.e2e.redes import Borda, SubnetOcupadaError, borda_da_suite

pytestmark = pytest.mark.slow

RAIZ = Path(__file__).resolve().parents[2]
COMPOSE = RAIZ / "docker" / "compose.yml"
COMPOSE_TESTE = RAIZ / "docker" / "compose.test.yml"
PROJETO = "sgs-api-e2e-keycloak"
PORTA_HTTP = "18083"
PORTA_HTTPS = "18446"
PUBLICA = f"https://localhost:{PORTA_HTTPS}"
KEYCLOAK = f"https://keycloak.localhost:{PORTA_HTTPS}"
# Lidos por tests/architecture/test_compose_configuracao.py: a API tem de aceitar esta configuração.
ARQUIVOS_COMPOSE = (COMPOSE, COMPOSE_TESTE)
AMBIENTE_COMPOSE = {
    "SGS_HTTP_PORT": PORTA_HTTP,
    "SGS_HTTPS_PORT": PORTA_HTTPS,
    "SGS_PUBLIC_URL": PUBLICA,
    "SGS_PUBLIC_KEYCLOAK_URL": KEYCLOAK,
}
ISSUER = f"{KEYCLOAK}/realms/sgs"
CALLBACK = f"{PUBLICA}/api/v1/auth/oidc/callback"
ENDPOINT_DE_TROCA = "https://keycloak:8443/realms/sgs/protocol/openid-connect/token"
SENHA = "sgs-lab-exemplo-usuario"  # docker/keycloak/realm-sgs.json
CHAVES_JWT = RAIZ / "secrets" / "jwt-keys.json"
CHAVES_DE_CIFRA = RAIZ / "secrets" / "crypto-keys.json"
DOCKER = shutil.which("docker")
CA_DO_CADDY = "/data/caddy/pki/authorities/local/root.crt"

type Resultado = subprocess.CompletedProcess[str]

_BORDA: list[Borda] = []

# Rodam dentro do contêiner da API, com a configuração OIDC do compose: a descoberta e o endpoint
# de token pela rede `integracoes`, conferindo o Keycloak pela CA de laboratório.
_DESCOBERTA_INTERNA = """
import os, ssl, urllib.request
contexto = ssl.create_default_context(cafile=os.environ["OIDC_CA_FILE"])
with urllib.request.urlopen(os.environ["OIDC_DISCOVERY_URL"], context=contexto, timeout=10) as r:
    print(r.read().decode())
"""
# Argumento: os campos do formulário em JSON. Autentica o cliente como a API fará (segredo).
_TROCA_PELA_API = """
import base64, json, os, ssl, sys, urllib.error, urllib.parse, urllib.request
contexto = ssl.create_default_context(cafile=os.environ["OIDC_CA_FILE"])
with urllib.request.urlopen(os.environ["OIDC_DISCOVERY_URL"], context=contexto, timeout=10) as r:
    endpoint = json.load(r)["token_endpoint"]
cliente = f'{os.environ["OIDC_CLIENT_ID"]}:{os.environ["OIDC_CLIENT_SECRET"]}'
pedido = urllib.request.Request(
    endpoint, data=urllib.parse.urlencode(json.loads(sys.argv[1])).encode(),
    headers={"Authorization": "Basic " + base64.b64encode(cliente.encode()).decode()})
try:
    with urllib.request.urlopen(pedido, context=contexto, timeout=10) as r:
        status, corpo = r.status, r.read()
except urllib.error.HTTPError as erro:
    status, corpo = erro.code, erro.read()
print(json.dumps({"endpoint": endpoint, "status": status, "corpo": json.loads(corpo)}))
"""
_PRONTA = """
import urllib.request
print(urllib.request.urlopen("http://127.0.0.1:8000/health/ready", timeout=5).status)
"""
# Imprime as portas do Keycloak que aceitam conexão TCP vindas da rede `integracoes`.
_PORTAS_ABERTAS = """
import socket
abertas = []
for porta in (8080, 8443, 9000):
    try:
        socket.create_connection(("keycloak", porta), timeout=3).close()
        abertas.append(porta)
    except OSError:
        pass
print(abertas)
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


def _troca_pela_api(campos: dict[str, str]) -> dict[str, Any]:
    resultado: dict[str, Any] = json.loads(_na_api(_TROCA_PELA_API, json.dumps(campos)))
    return resultado


class _Loopback(httpx.HTTPTransport):
    """Leva `keycloak.localhost` a 127.0.0.1 (a porta publicada do Caddy). O `Host` e o SNI, e com
    ele a conferência do certificado, continuam com o nome, como no navegador."""

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        nome = request.url.host
        if nome == "keycloak.localhost":
            request = httpx.Request(
                request.method,
                request.url.copy_with(host="127.0.0.1"),
                headers=request.headers,
                content=request.content,
                extensions={**request.extensions, "sni_hostname": nome},
            )
        return super().handle_request(request)


@pytest.fixture(scope="module")
def ca_do_caddy(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    if DOCKER is None:
        pytest.skip("Docker não encontrado")
    try:
        _BORDA[:] = [borda_da_suite("KEYCLOAK", DOCKER, projeto=PROJETO)]
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
        subida = _compose(
            "up", "-d", "--build", "--wait", "proxy", "keycloak", check=False, timeout=900
        )
        if subida.returncode != 0:
            logs = _compose("logs", "--no-color", "--tail", "100", check=False)
            pytest.fail(f"o compose não subiu:\n{subida.stderr}\n{logs.stdout}")
        ca = tmp_path_factory.mktemp("caddy") / "root.crt"
        _compose("cp", f"proxy:{CA_DO_CADDY}", str(ca))
        yield ca
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


@pytest.fixture
def navegador(ca_do_caddy: Path) -> Iterator[httpx.Client]:
    """Um navegador novo por teste (cookies próprios), confiando só na CA do Caddy."""
    contexto = ssl.create_default_context(cafile=str(ca_do_caddy))
    with httpx.Client(transport=_Loopback(verify=contexto), timeout=20) as cliente:
        yield cliente


def _pkce() -> tuple[str, str]:
    verificador = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verificador.encode()).digest()
    return verificador, base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def _autorizar(
    navegador: httpx.Client, extras: dict[str, str], *, redirect_uri: str = CALLBACK
) -> httpx.Response:
    parametros = {
        "client_id": "sgs-api",
        "response_type": "code",
        "scope": "openid profile email",
        "redirect_uri": redirect_uri,
        "state": secrets.token_urlsafe(32),
        **extras,
    }
    return navegador.get(f"{ISSUER}/protocol/openid-connect/auth", params=parametros)


def _consulta(resposta: httpx.Response) -> dict[str, list[str]]:
    """Parâmetros do redirecionamento ao callback, que o teste não segue."""
    assert resposta.status_code == 302, resposta.text
    destino = resposta.headers["location"]
    assert destino.startswith(f"{CALLBACK}?"), destino
    return parse_qs(urlsplit(destino).query)


def _codigo(navegador: httpx.Client, usuario: str, desafio: str, nonce: str) -> str:
    """Faz o login pela tela do Keycloak e devolve o código entregue ao callback."""
    tela = _autorizar(
        navegador, {"code_challenge": desafio, "code_challenge_method": "S256", "nonce": nonce}
    )
    assert tela.status_code == 200, tela.text
    formulario = re.search(r'<form\b[^>]*\bid="kc-form-login"[^>]*>', tela.text)
    assert formulario is not None, tela.text
    acao = re.search(r'\baction="([^"]+)"', formulario.group(0))
    assert acao is not None
    resposta = navegador.post(
        html.unescape(acao.group(1)), data={"username": usuario, "password": SENHA}
    )
    consulta = _consulta(resposta)
    assert consulta["iss"] == [ISSUER]  # RFC 9207: o mesmo emissor na resposta de autorização
    [codigo] = consulta["code"]
    return codigo


def _claims(jwt: str) -> dict[str, Any]:
    """Só o conteúdo do token (a assinatura é conferida pela API, na 004/T6)."""
    conteudo = jwt.split(".")[1]
    claims: dict[str, Any] = json.loads(
        base64.urlsafe_b64decode(conteudo + "=" * (-len(conteudo) % 4))
    )
    return claims


def test_issuer_e_o_mesmo_pela_descoberta_publica_e_pela_interna(navegador: httpx.Client) -> None:
    """004/R5.2 (design § Riscos): o `iss` não depende do caminho; a API pega o JWKS e troca o
    código direto no Keycloak, e o navegador vai ao endereço público."""
    publica = navegador.get(f"{ISSUER}/.well-known/openid-configuration").raise_for_status().json()
    interna = json.loads(_na_api(_DESCOBERTA_INTERNA))

    assert publica["issuer"] == ISSUER
    assert interna["issuer"] == ISSUER
    autorizacao = f"{ISSUER}/protocol/openid-connect/auth"
    assert publica["authorization_endpoint"] == autorizacao
    assert interna["authorization_endpoint"] == autorizacao
    assert interna["token_endpoint"] == ENDPOINT_DE_TROCA
    assert interna["jwks_uri"] == "https://keycloak:8443/realms/sgs/protocol/openid-connect/certs"


def test_keycloak_so_atende_https_na_rede(ca_do_caddy: Path) -> None:
    """004 design § Keycloak (`KC_HTTP_ENABLED=false`): só a 8443 aceita conexão; a 8080 do HTTP
    e a 9000 da saúde (só no loopback) ficam fechadas. Por isso o modo `start`, e não o
    `start-dev`, que abre a 8080 mesmo assim."""
    assert _na_api(_PORTAS_ABERTAS).strip() == "[8443]"


def test_cliente_exige_pkce_s256_e_a_redirect_uri_exata(navegador: httpx.Client) -> None:
    """004/R5.2: cliente confidencial com PKCE S256, só standard flow."""
    verificador, desafio = _pkce()
    s256 = {"code_challenge": desafio, "code_challenge_method": "S256"}

    for sem_s256 in ({}, {"code_challenge": verificador, "code_challenge_method": "plain"}):
        consulta = _consulta(_autorizar(navegador, sem_s256))
        assert consulta["error"] == ["invalid_request"]
        assert "code" not in consulta

    # Redirect URI que não é a exata: o Keycloak para na própria página, sem redirecionar.
    outra = _autorizar(navegador, s256, redirect_uri=f"{CALLBACK}/../outra")
    assert outra.status_code == 400
    assert "location" not in outra.headers

    # O código só vale com o verificador certo.
    codigo = _codigo(navegador, "oidc.auditor", desafio, secrets.token_urlsafe(32))
    troca = _troca_pela_api(
        {
            "grant_type": "authorization_code",
            "code": codigo,
            "code_verifier": _pkce()[0],
            "redirect_uri": CALLBACK,
        }
    )
    assert troca["status"] == 400
    assert troca["corpo"]["error"] == "invalid_grant"

    # Sem senha direta (direct access grants desligado).
    senha = _troca_pela_api(
        {"grant_type": "password", "username": "oidc.auditor", "password": SENHA}
    )
    assert senha["status"] in {400, 401}
    assert senha["corpo"]["error"] == "unauthorized_client"


def test_id_token_traz_a_claim_groups(navegador: httpx.Client) -> None:
    """004/R5.2 (claim de grupos da R3.3): login de um usuário de exemplo pelo Caddy e troca do
    código pela API, pela rede interna."""
    verificador, desafio = _pkce()
    nonce = secrets.token_urlsafe(32)
    codigo = _codigo(navegador, "oidc.tecnico.ds4", desafio, nonce)

    troca = _troca_pela_api(
        {
            "grant_type": "authorization_code",
            "code": codigo,
            "code_verifier": verificador,
            "redirect_uri": CALLBACK,
        }
    )

    assert troca["endpoint"] == ENDPOINT_DE_TROCA
    assert troca["status"] == 200, troca["corpo"]
    claims = _claims(troca["corpo"]["id_token"])
    assert claims["iss"] == ISSUER
    assert claims["aud"] in ("sgs-api", ["sgs-api"])
    assert claims["nonce"] == nonce
    assert claims["preferred_username"] == "oidc.tecnico.ds4"
    assert claims["email_verified"] is True
    assert claims["groups"] == ["oidc-tecnico-ds-iv"]


def test_servicos_certs_gera_os_tres_certificados_sem_a_chave_da_ca(ca_do_caddy: Path) -> None:
    """004 design § Certificados (compartilhado com a 005): cada chave com o uid do usuário do
    contêiner do serviço, modo 0600; a API e o proxy veem só a CA."""
    comando = "find /certs -type f -exec stat -c '%n %u %a' {} +"
    listagem = _compose(
        "run", "--rm", "--no-deps", "--entrypoint", "sh", "servicos-certs", "-c", comando
    ).stdout

    assert sorted(listagem.splitlines()) == [
        "/certs/ca/ca.crt 0 644",
        "/certs/keycloak/server.crt 0 644",
        "/certs/keycloak/server.key 1000 600",
        "/certs/ldap/server.crt 0 644",
        "/certs/ldap/server.key 389 600",
        "/certs/s3/server.crt 0 644",
        "/certs/s3/server.key 1000 600",
    ]
    for servico in ("api", "proxy"):
        assert _compose("exec", "-T", servico, "ls", "/certs-servicos").stdout.split() == ["ca.crt"]


def test_api_fica_pronta_sem_o_keycloak(ca_do_caddy: Path) -> None:
    """004 design § Caddy e compose: o provedor só é chamado no uso. Último do arquivo: para o
    Keycloak."""
    _compose("stop", "keycloak")
    assert _na_api(_PRONTA).strip() == "200"
