"""Login LDAP com 2FA e login OIDC pelo navegador contra o compose (spec 004, T14; R5.3, R3.9;
design § Roteiro e ferramenta).

Sobe `proxy`, `ldap` e `keycloak` do docker/compose.yml (com `api`, `db` e os certificados) num
projeto próprio (`sgs-api-e2e-login`), com portas e subnet de borda próprias
(`tests/e2e/redes.py`), e derruba só esse projeto, com os volumes dele, no fim. Segue os passos
3 a 5 de `docs/operacao/demo-diretorio.md`, pelo Caddy:

- um Admin TI local sincroniza o diretório e mapeia `sgs-tecnico-ds3` para `TECNICO_DISTRITAL`
  no DS-III (003/R3.1);
- `ldap.tecnico.ds3` entra por LDAP com o cadastro do 2FA (`pyotp`), e o `/me` traz o papel
  derivado do grupo (R2.1, R2.3);
- `oidc.tecnico.ds4` entra pelo botão da tela de login, no Keycloak, num Chromium do host; o
  callback volta ao front sem token na URL, e o front abre a sessão pela renovação até o `/me`
  (R3.1 a R3.4, R3.9).

Fica fora do `make check`; rodar à parte com `uv run pytest tests/e2e/test_login_ldap_oidc.py -m
slow`.
"""

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
from playwright.sync_api import Browser, sync_playwright
from playwright.sync_api import Error as ErroDoPlaywright

from tests.e2e import segredos
from tests.e2e.redes import Borda, SubnetOcupadaError, borda_da_suite

pytestmark = pytest.mark.slow

RAIZ = Path(__file__).resolve().parents[2]
COMPOSE = RAIZ / "docker" / "compose.yml"
COMPOSE_TESTE = RAIZ / "docker" / "compose.test.yml"
PROJETO = "sgs-api-e2e-login"
PORTA_HTTP = "18085"
PORTA_HTTPS = "18448"
PUBLICA = f"https://localhost:{PORTA_HTTPS}"
# Lidos por tests/architecture/test_compose_configuracao.py: a API tem de aceitar esta configuração.
ARQUIVOS_COMPOSE = (COMPOSE, COMPOSE_TESTE)
AMBIENTE_COMPOSE = {
    "SGS_HTTP_PORT": PORTA_HTTP,
    "SGS_HTTPS_PORT": PORTA_HTTPS,
    "SGS_PUBLIC_URL": PUBLICA,
    "SGS_PUBLIC_KEYCLOAK_URL": f"https://keycloak.localhost:{PORTA_HTTPS}",
    "SGS_PUBLIC_S3_URL": f"https://s3.localhost:{PORTA_HTTPS}",
}
DOCKER = shutil.which("docker")
CA_DO_CADDY = "/data/caddy/pki/authorities/local/root.crt"
ADMIN = "admin.e2e.login"
SENHA_DO_LABORATORIO = "sgs-lab-exemplo-usuario"  # README § Diretório LDAP e § Provedor OIDC

type Resultado = subprocess.CompletedProcess[str]

_BORDA: list[Borda] = []


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


@pytest.fixture(scope="module")
def ambiente(tmp_path_factory: pytest.TempPathFactory) -> Iterator[dict[str, Any]]:
    if DOCKER is None:
        pytest.skip("Docker não encontrado")
    try:
        _BORDA[:] = [borda_da_suite("LOGIN", DOCKER, projeto=PROJETO)]
    except SubnetOcupadaError as erro:
        pytest.skip(str(erro))
    criados = segredos.criar_faltando()
    senha = secrets.token_urlsafe(16)
    try:
        subida = _compose(
            "up", "-d", "--build", "--wait", "proxy", "ldap", "keycloak", check=False, timeout=900
        )
        if subida.returncode != 0:
            logs = _compose("logs", "--no-color", "--tail", "100", check=False)
            pytest.fail(f"o compose não subiu:\n{subida.stderr}\n{logs.stdout}")
        _compose(
            "exec",
            "-T",
            "-e",
            f"SGS_SENHA_INICIAL={senha}",
            "api",
            "sgs-admin",
            "create-user",
            "--username",
            ADMIN,
            "--nome",
            "Admin TI (e2e)",
        )
        ca = tmp_path_factory.mktemp("caddy") / "root.crt"
        _compose("cp", f"proxy:{CA_DO_CADDY}", str(ca))
        distrito = _compose(
            "exec",
            "-T",
            "db",
            "psql",
            "-U",
            "sgs",
            "sgs",
            "-Atc",
            "SELECT id FROM districts WHERE code = 'DS-III'",
        ).stdout.strip()
        yield {"ca": ca, "senha": senha, "ds3": distrito}
    finally:
        # Só o projeto descartável deste arquivo, pelo nome, com os volumes dele.
        _compose("down", "-v", "--remove-orphans", check=False, timeout=300)
        segredos.apagar(criados)


@pytest.fixture(scope="module")
def api(ambiente: dict[str, Any]) -> Iterator[httpx.Client]:
    """A API pelo Caddy, confiando só na CA dele."""
    contexto = ssl.create_default_context(cafile=str(ambiente["ca"]))
    with httpx.Client(base_url=f"{PUBLICA}/api/v1", verify=contexto, timeout=30) as cliente:
        yield cliente


def _entrar(api: httpx.Client, usuario: str, senha: str, provider: str = "local") -> str:
    """Login da 002 com o cadastro do 2FA (`pyotp`); devolve o access token."""
    login = api.post(
        "/auth/login", json={"username": usuario, "password": senha, "provider": provider}
    )
    assert login.status_code == 200, login.text
    assert login.json()["mfa_enrollment_required"] is True
    desafio = login.json()["mfa_token"]
    uri = api.post("/auth/mfa/enroll", json={"mfa_token": desafio}).json()["otpauth_uri"]
    segredo = parse_qs(urlsplit(uri).query)["secret"][0]
    confirmado = api.post(
        "/auth/mfa/confirm", json={"mfa_token": desafio, "code": pyotp.TOTP(segredo).now()}
    )
    assert confirmado.status_code == 200, confirmado.text
    token: str = confirmado.json()["access_token"]
    return token


@pytest.fixture(scope="module")
def admin(api: httpx.Client, ambiente: dict[str, Any]) -> dict[str, str]:
    """O Admin TI, com o diretório já sincronizado."""
    cabecalho = {"Authorization": f"Bearer {_entrar(api, ADMIN, ambiente['senha'])}"}
    execucao = api.post("/admin/diretorio/sincronizar", headers=cabecalho).json()["execucao_id"]
    for _ in range(60):
        status = api.get(f"/admin/diretorio/execucoes/{execucao}", headers=cabecalho).json()
        if status["status"] != "em_andamento":
            break
        time.sleep(1)
    assert status["status"] == "concluida", status
    return cabecalho


def _grupo(api: httpx.Client, admin: dict[str, str], origem: str, nome: str) -> dict[str, Any]:
    resposta = api.get(
        "/admin/diretorio/grupos", params={"origem": origem, "busca": nome}, headers=admin
    )
    [grupo] = [g for g in resposta.json()["itens"] if g["nome"] == nome]
    return dict(grupo)


def test_login_ldap_com_2fa_traz_o_papel_do_grupo_mapeado(
    api: httpx.Client, admin: dict[str, str], ambiente: dict[str, Any]
) -> None:
    """004/R2.1, R2.3, R5.3; 003/R3.1 (roteiro, passos 3 e 4)"""
    grupo = _grupo(api, admin, "ldap", "sgs-tecnico-ds3")
    mapeamento = api.post(
        "/admin/mapeamentos-grupo",
        json={
            "grupo_id": grupo["id"],
            "papel": "TECNICO_DISTRITAL",
            "escopo_tipo": "distrito",
            "escopo_id": ambiente["ds3"],
        },
        headers=admin,
    )
    assert mapeamento.status_code == 201, mapeamento.text

    token = _entrar(api, "ldap.tecnico.ds3", SENHA_DO_LABORATORIO, provider="ldap")
    me = api.get("/me", headers={"Authorization": f"Bearer {token}"}).json()

    assert (me["username"], me["origem"]) == ("ldap.tecnico.ds3", "ldap")
    papeis = {(p["papel"], p["escopo_tipo"], p["escopo_id"], p["origem"]) for p in me["papeis"]}
    assert ("TECNICO_DISTRITAL", "distrito", ambiente["ds3"], "group") in papeis
    errada = api.post(
        "/auth/login",
        json={"username": "ldap.tecnico.ds3", "password": "senha-errada", "provider": "ldap"},
    )
    assert errada.status_code == 401


def _navegador(p: Any) -> Browser:
    try:
        navegador: Browser = p.chromium.launch()
    except ErroDoPlaywright:
        chromium = shutil.which("chromium")
        if chromium is None:
            pytest.skip("sem Chromium para o Playwright (`uv run playwright install chromium`)")
        navegador = p.chromium.launch(executable_path=chromium)
    return navegador


def test_login_oidc_pelo_navegador_ate_o_me(
    api: httpx.Client, admin: dict[str, str], ambiente: dict[str, Any]
) -> None:
    """004/R3.1 a R3.4, R3.9, R5.3 (roteiro, passo 5: botão da tela, Keycloak, callback,
    renovação e `/me`, sem token na URL)"""
    with sync_playwright() as p:
        navegador = _navegador(p)
        try:
            # CA interna do Caddy só de teste; a conferência do certificado em si é da 012/T1.
            contexto = navegador.new_context(base_url=PUBLICA, ignore_https_errors=True)
            pagina = contexto.new_page()
            enderecos: list[str] = []
            # Cada salto de um redirecionamento é uma requisição de navegação própria.
            pagina.on(
                "request",
                lambda pedido: (
                    enderecos.append(pedido.url) if pedido.is_navigation_request() else None
                ),
            )
            pagina.goto("/")
            pagina.get_by_text("Entrar pelo provedor de identidade").click()
            pagina.wait_for_url("**/realms/sgs/**")
            pagina.fill("#username", "oidc.tecnico.ds4")
            pagina.fill("#password", SENHA_DO_LABORATORIO)
            with pagina.expect_response(
                lambda r: r.url.endswith("/api/v1/me") and r.status == 200, timeout=30_000
            ) as resposta:
                pagina.click("#kc-login")
            me = json.loads(resposta.value.text())
        finally:
            navegador.close()

    assert (me["username"], me["origem"]) == ("oidc.tecnico.ds4", "oidc")
    callback = [e for e in enderecos if "/api/v1/auth/oidc/callback" in e]
    assert callback, enderecos
    voltas = [e for e in enderecos if e.startswith(PUBLICA) and "/api/v1/" not in e]
    assert voltas
    assert all("token" not in parse_qs(urlsplit(e).query) for e in voltas)
    assert all("login_erro" not in e for e in voltas)
    grupo = _grupo(api, admin, "oidc", "oidc-tecnico-ds-iv")
    assert grupo["membros_ativos"] == 1
