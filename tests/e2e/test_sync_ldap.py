"""Sincronização do diretório e recusa do certificado LDAP contra o compose (spec 004, T14; R5.3,
R1.13; design § Roteiro e ferramenta).

Sobe `api` e `ldap` do docker/compose.yml (com `db` e os certificados) num projeto próprio
(`sgs-api-e2e-sync-ldap`), com subnet de borda própria (`tests/e2e/redes.py`), e derruba só esse
projeto, com os volumes dele, no fim. Segue os passos 1, 2 e 6 de `docs/operacao/demo-diretorio.md`,
pela API de dentro do contêiner (sem o proxy):

- a primeira sincronização cria as pessoas e os grupos da carga inicial (R1.5, R1.8);
- depois de mudar um nome e apagar uma pessoa no diretório, a seguinte atualiza e desativa
  (R1.6, R1.7), sem apagar a conta;
- o `sgs-admin diretorio testar` responde `ok` com a configuração do compose e recusa por
  certificado a CA do banco e o alias `ldap-nome-errado`, antes de qualquer *bind* (R1.13).

Fica fora do `make check`; rodar à parte com `uv run pytest tests/e2e/test_sync_ldap.py -m slow`.
"""

import json
import os
import secrets
import shutil
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pyotp
import pytest

from tests.e2e import segredos
from tests.e2e.redes import Borda, SubnetOcupadaError, borda_da_suite

pytestmark = pytest.mark.slow

RAIZ = Path(__file__).resolve().parents[2]
COMPOSE = RAIZ / "docker" / "compose.yml"
COMPOSE_TESTE = RAIZ / "docker" / "compose.test.yml"
PROJETO = "sgs-api-e2e-sync-ldap"
# Lidos por tests/architecture/test_compose_configuracao.py: a API tem de aceitar esta configuração.
ARQUIVOS_COMPOSE = (COMPOSE, COMPOSE_TESTE)
AMBIENTE_COMPOSE: dict[str, str] = {}
DOCKER = shutil.which("docker")
BASE = "dc=recife,dc=pe,dc=gov,dc=br"
ADMIN = "admin.e2e.sync"

type Resultado = subprocess.CompletedProcess[str]

_BORDA: list[Borda] = []

# Roda dentro do contêiner da API: a API sem o proxy, pelo loopback, como o healthcheck.
# Argumentos: método, caminho, corpo JSON (ou ""), access token (ou "").
_CHAMADA = """
import json, sys, urllib.error, urllib.request
metodo, caminho, corpo, token = sys.argv[1:5]
pedido = urllib.request.Request("http://127.0.0.1:8000" + caminho, method=metodo,
    data=corpo.encode() if corpo else None,
    headers={"Content-Type": "application/json"}
    | ({"Authorization": "Bearer " + token} if token else {}))
try:
    with urllib.request.urlopen(pedido, timeout=30) as r:
        status, dados = r.status, r.read()
except urllib.error.HTTPError as erro:
    status, dados = erro.code, erro.read()
print(json.dumps({"status": status, "corpo": json.loads(dados) if dados else None}))
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


def _api(metodo: str, caminho: str, corpo: Any = None, token: str = "") -> dict[str, Any]:
    saida = _compose(
        "exec",
        "-T",
        "api",
        "python",
        "-c",
        _CHAMADA,
        metodo,
        caminho,
        "" if corpo is None else json.dumps(corpo),
        token,
    ).stdout
    resposta: dict[str, Any] = json.loads(saida)
    return resposta


def _ldap(*comando: str, ldif: str = "") -> Resultado:
    assert DOCKER is not None
    arquivos = [*(a for f in ARQUIVOS_COMPOSE for a in ("-f", str(f))), "-p", PROJETO]
    # Comandos fixos deste arquivo, sem entrada externa.
    return subprocess.run(  # noqa: S603
        [DOCKER, "compose", *arquivos, "exec", "-T", "ldap", *comando],
        input=ldif,
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
        cwd=RAIZ,
        env=os.environ | AMBIENTE_COMPOSE | _BORDA[0].ambiente(),
    )


@pytest.fixture(scope="module")
def admin() -> Iterator[str]:
    """O compose de pé e o access token de um Admin TI local (com o 2FA cadastrado)."""
    if DOCKER is None:
        pytest.skip("Docker não encontrado")
    try:
        _BORDA[:] = [borda_da_suite("SYNC_LDAP", DOCKER, projeto=PROJETO)]
    except SubnetOcupadaError as erro:
        pytest.skip(str(erro))
    criados = segredos.criar_faltando()
    senha = secrets.token_urlsafe(16)
    try:
        subida = _compose("up", "-d", "--build", "--wait", "api", "ldap", check=False, timeout=900)
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
        yield _entrar(ADMIN, senha)
    finally:
        # Só o projeto descartável deste arquivo, pelo nome, com os volumes dele.
        _compose("down", "-v", "--remove-orphans", check=False, timeout=300)
        segredos.apagar(criados)


def _entrar(usuario: str, senha: str, provider: str = "local") -> str:
    """Login da 002 com o cadastro do 2FA (`pyotp`); devolve o access token."""
    login = _api(
        "POST", "/api/v1/auth/login", {"username": usuario, "password": senha, "provider": provider}
    )
    assert login["status"] == 200, login
    desafio = login["corpo"]["mfa_token"]
    uri = _api("POST", "/api/v1/auth/mfa/enroll", {"mfa_token": desafio})["corpo"]["otpauth_uri"]
    segredo = parse_qs(urlsplit(uri).query)["secret"][0]
    confirmado = _api(
        "POST",
        "/api/v1/auth/mfa/confirm",
        {"mfa_token": desafio, "code": pyotp.TOTP(segredo).now()},
    )
    assert confirmado["status"] == 200, confirmado
    token: str = confirmado["corpo"]["access_token"]
    return token


def _sincronizar(admin: str) -> dict[str, Any]:
    disparo = _api("POST", "/api/v1/admin/diretorio/sincronizar", token=admin)
    assert disparo["status"] == 202, disparo
    execucao = disparo["corpo"]["execucao_id"]
    for _ in range(60):
        corpo: dict[str, Any] = _api(
            "GET", f"/api/v1/admin/diretorio/execucoes/{execucao}", token=admin
        )["corpo"]
        if corpo["status"] != "em_andamento":
            return corpo
        time.sleep(1)
    pytest.fail("a sincronização não terminou em 60 s")


def test_sincronizacao_cria_altera_e_desativa(admin: str) -> None:
    """004/R5.3, R1.5 a R1.8 (roteiro, passos 1 e 2)"""
    primeira = _sincronizar(admin)
    assert primeira["status"] == "concluida", primeira
    assert primeira["usuarios"]["criados"] == 8  # um por papel da 003, mais ldap.temporario
    assert primeira["grupos"]["criados"] == 7
    assert primeira["conflitos"] == []

    _ldap(
        "ldapmodify",
        "-Y",
        "EXTERNAL",
        "-H",
        "ldapi:///",
        ldif=(
            f"dn: uid=ldap.diretoria,ou=pessoas,{BASE}\nchangetype: modify\nreplace: cn\n"
            "cn: Diretoria Executiva (e2e)\n"
        ),
    )
    _ldap(
        "ldapdelete", "-Y", "EXTERNAL", "-H", "ldapi:///", f"uid=ldap.temporario,ou=pessoas,{BASE}"
    )
    segunda = _sincronizar(admin)

    assert segunda["status"] == "concluida", segunda
    assert segunda["usuarios"]["criados"] == 0
    assert segunda["usuarios"]["desativados"] == 1
    grupos = _api("GET", "/api/v1/admin/diretorio/grupos?origem=ldap", token=admin)["corpo"]
    assert grupos["total"] == 7


@pytest.mark.parametrize(
    ("argumentos", "esperado"),
    [
        pytest.param((), "ok", id="configuracao-do-compose"),
        pytest.param(("--ca", "/certs/ca.crt"), "certificado", id="ca-do-banco"),
        pytest.param(("--url", "ldaps://ldap-nome-errado:636"), "certificado", id="nome-errado"),
    ],
)
def test_sgs_admin_diretorio_testar_recusa_o_certificado(
    admin: str, argumentos: tuple[str, ...], esperado: str
) -> None:
    """004/R1.13 (roteiro, passo 6: a recusa vem antes de qualquer bind)"""
    resultado = _compose(
        "exec", "-T", "api", "sgs-admin", "diretorio", "testar", *argumentos, check=False
    )

    saida = resultado.stdout + resultado.stderr
    assert esperado in saida, saida
    assert (resultado.returncode == 0) is (esperado == "ok"), saida
