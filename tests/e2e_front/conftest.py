"""Infraestrutura dos E2E do front (spec 012, tasks § T2; ADR-0011).

Sobe o compose da T1 num projeto próprio, com portas alternativas, carrega o `sgs-admin seed demo`
com uma senha gerada aqui e abre o navegador do Playwright (Python). Usa o Chromium do Playwright
ou, na falta dele, o Chrome do sistema. Tudo é derrubado no fim, com os volumes.

O login tem limite de 10 por minuto por IP (002/R1.5): cada papel entra uma vez por execução e a
sessão é reaproveitada pelo cookie de refresh; se a API responder 429, a fixture espera a janela.
"""

import os
import secrets
import shutil
import subprocess
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pyotp
import pytest
from playwright.sync_api import Browser, BrowserContext, Page, expect, sync_playwright
from playwright.sync_api import Error as ErroDoPlaywright

from src.tools import crypto_keys, jwt_keys
from tests.e2e import segredos
from tests.e2e.redes import Borda, SubnetOcupadaError, borda_da_suite

RAIZ = Path(__file__).resolve().parents[2]
COMPOSE = RAIZ / "docker" / "compose.yml"
COMPOSE_TESTE = RAIZ / "docker" / "compose.test.yml"
PROJETO = "sgs-api-e2e-front-ui"
PORTA_HTTP = "18081"
PORTA_HTTPS = "18444"
BASE = f"https://localhost:{PORTA_HTTPS}"
# Lidos por tests/architecture/test_compose_configuracao.py: a API tem de aceitar esta configuração.
ARQUIVOS_COMPOSE = (COMPOSE, COMPOSE_TESTE)
AMBIENTE_COMPOSE = {
    "SGS_HTTP_PORT": PORTA_HTTP,
    "SGS_HTTPS_PORT": PORTA_HTTPS,
    "SGS_CORS_ORIGINS": BASE,  # o refresh confere a Origin (002/R3.6; spec 012, R2.4)
    # FRONTEND_URL sai daqui, e a API exige a origem dele em CORS_ORIGINS (004/T6).
    "SGS_PUBLIC_URL": BASE,
    # Spec 014: a URL pré-assinada do download aponta o S3 de laboratório na porta da suíte.
    "SGS_PUBLIC_S3_URL": f"https://s3.localhost:{PORTA_HTTPS}",
}
CHAVES_JWT = RAIZ / "secrets" / "jwt-keys.json"
CHAVES_DE_CIFRA = RAIZ / "secrets" / "crypto-keys.json"
DOCKER = shutil.which("docker")

# Perfis de referência (spec 012, P2) e os demais papéis, todos do seed de demonstração (010).
USUARIOS = {
    "GESTOR_DADOS": "demo.carla.dias",
    "TECNICO_DISTRITAL": "demo.nicolas.brito",  # DS-IV
    "GESTOR_UNIDADE": "demo.sofia.barros",  # CAPS II Espaço Azul
    "COORD_TECNICO": "demo.gabriela.reis",
    "DIRETORIA": "demo.yara.duarte",
    "AUDITOR": "demo.bento.sa",
    "ADMIN_TI": "demo.ana.lima",
}


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if Path(str(item.fspath)).parent == Path(__file__).parent:
            item.add_marker(pytest.mark.slow)


_BORDA: list[Borda] = []
"""Subnet de borda da suíte (spec 013, T4), escolhida antes do `up`."""


def _compose(
    *args: str, check: bool = True, timeout: int = 120
) -> subprocess.CompletedProcess[str]:
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


@pytest.fixture(scope="session")
def senha_demo() -> Iterator[str]:
    if DOCKER is None:
        pytest.skip("Docker não encontrado")
    try:
        _BORDA[:] = [borda_da_suite("FRONT_UI", DOCKER, projeto=PROJETO)]
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
    senha = secrets.token_urlsafe(16)
    try:
        # Spec 014: relatórios (s3, s3-init) e sincronização do diretório (ldap).
        servicos = ("proxy", "ldap", "s3", "s3-init")
        subida = _compose("up", "-d", "--build", "--wait", *servicos, check=False, timeout=900)
        if subida.returncode != 0:
            logs = _compose("logs", "--no-color", "--tail", "100", check=False)
            pytest.fail(f"o compose não subiu:\n{subida.stderr}\n{logs.stdout}")
        seed = _compose(
            "exec",
            "-T",
            "-e",
            f"SGS_SEED_SENHA={senha}",
            "api",
            "sgs-admin",
            "seed",
            "demo",
            check=False,
            timeout=300,
        )
        if seed.returncode != 0:
            pytest.fail(f"o seed demo falhou:\n{seed.stderr}\n{seed.stdout}")
        yield senha
    finally:
        _compose("down", "-v", "--remove-orphans", check=False, timeout=300)
        if criou_chave:
            CHAVES_JWT.unlink(missing_ok=True)
        if criou_cifra:
            CHAVES_DE_CIFRA.unlink(missing_ok=True)
        segredos.apagar(segredos_da_005)
        if criou_pasta:
            CHAVES_JWT.parent.rmdir()


@pytest.fixture(scope="session")
def navegador(senha_demo: str) -> Iterator[Browser]:
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except ErroDoPlaywright:
            browser = p.chromium.launch(channel="chrome")
        _aquecer(browser)
        yield browser
        browser.close()


def _aquecer(navegador: Browser) -> None:
    """Logo depois da subida, a rede do Docker ainda muda e o Chrome aborta a navegação
    (ERR_NETWORK_CHANGED); a primeira abertura é repetida até a rede estabilizar."""
    contexto = novo_contexto(navegador)
    pagina = contexto.new_page()
    for tentativa in range(10):
        try:
            pagina.goto("/health/ready")
            break
        except ErroDoPlaywright:
            if tentativa == 9:
                raise
            time.sleep(2)
    contexto.close()


def novo_contexto(navegador: Browser) -> BrowserContext:
    # CA interna do Caddy só de teste; a verificação do certificado em si é coberta pela T1.
    return navegador.new_context(base_url=BASE, ignore_https_errors=True, locale="pt-BR")


@dataclass
class Autenticador:
    """Segredos TOTP cadastrados nesta execução e o último passo usado (o código não se repete)."""

    segredos: dict[str, str] = field(default_factory=dict)
    ultimo_passo: dict[str, int] = field(default_factory=dict)

    def codigo(self, usuario: str) -> str:
        totp = pyotp.TOTP(self.segredos[usuario])
        while int(time.time()) // totp.interval == self.ultimo_passo.get(usuario):
            time.sleep(1)  # espera o próximo passo de 30 s para não reusar o código
        self.ultimo_passo[usuario] = int(time.time()) // totp.interval
        return totp.now()


@pytest.fixture(scope="session")
def autenticador() -> Autenticador:
    return Autenticador()


def preencher_login(pagina: Page, usuario: str, senha: str) -> None:
    """Envia usuário e senha; se a API limitar (429), espera a janela de 1 minuto e repete."""
    for _ in range(3):
        pagina.fill("#lg-user", usuario)
        pagina.fill("#lg-pass", senha)
        with pagina.expect_response("**/api/v1/auth/login") as resposta:
            pagina.click("#loginForm button[type=submit]")
        if resposta.value.status != 429:
            return
        time.sleep(61)
    pytest.fail("login limitado (429) três vezes seguidas")


def entrar(pagina: Page, usuario: str, senha: str, autenticador: Autenticador) -> None:
    """Login completo pela tela: cadastro do 2FA no primeiro acesso, verificação depois."""
    pagina.goto("/")
    expect(pagina.locator("#lg-user")).to_be_visible()
    preencher_login(pagina, usuario, senha)
    codigo = pagina.locator("#lg-code")
    expect(codigo).to_be_visible()
    chave = pagina.locator("#lg-key")
    if chave.count():
        autenticador.segredos[usuario] = chave.input_value()
    codigo.fill(autenticador.codigo(usuario))  # 6 dígitos enviam o formulário
    expect(pagina.locator(".shell")).to_be_visible()


@pytest.fixture(scope="session")
def sessao_de(
    navegador: Browser, senha_demo: str, autenticador: Autenticador
) -> Iterator[Callable[[str], Page]]:
    """Página já autenticada para um papel; o contexto (cookie de refresh) é reaproveitado."""
    contextos: dict[str, BrowserContext] = {}

    def abrir(papel: str) -> Page:
        usuario = USUARIOS[papel]
        if usuario not in contextos:
            contexto = novo_contexto(navegador)
            entrar(contexto.new_page(), usuario, senha_demo, autenticador)
            contextos[usuario] = contexto
        pagina = contextos[usuario].new_page()
        pagina.goto("/")
        expect(pagina.locator(".shell")).to_be_visible()
        return pagina

    yield abrir
    for contexto in contextos.values():
        contexto.close()


@pytest.fixture
def pagina_anonima(navegador: Browser) -> Iterator[Page]:
    contexto = novo_contexto(navegador)
    yield contexto.new_page()
    contexto.close()
