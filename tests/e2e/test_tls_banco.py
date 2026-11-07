"""TLS entre a API e o PostgreSQL no compose (spec 011, R10.3 a R10.5).

Sobe `db-certs`, `db` e `api` do docker/compose.yml num projeto próprio, para não tocar nos
volumes do ambiente de desenvolvimento, e derruba tudo, com os volumes, no fim. Fica fora do
`make check`; rodar à parte com `uv run pytest tests/e2e/test_tls_banco.py -m slow`.
"""

import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from src.tools import jwt_keys

pytestmark = pytest.mark.slow

RAIZ = Path(__file__).resolve().parents[2]
COMPOSE = RAIZ / "docker" / "compose.yml"
PROJETO = "sgs-api-e2e-tls"
CHAVES_JWT = RAIZ / "secrets" / "jwt-keys.json"
DOCKER = shutil.which("docker")
GIT = shutil.which("git")

# Extensões de chave e certificado que nunca podem estar no repositório (R10.5).
EXTENSOES_PROIBIDAS = frozenset({".pem", ".key", ".crt", ".csr", ".p12", ".pfx", ".srl"})

# Roda dentro do container da API e chama /health/ready; imprime "status corpo".
_PRONTA = """
import urllib.error, urllib.request
try:
    resposta = urllib.request.urlopen("http://127.0.0.1:8000/health/ready", timeout=5)
except urllib.error.HTTPError as erro:
    resposta = erro
print(resposta.status, resposta.read().decode())
"""

# Roda dentro do container da API e conecta ao banco com o mesmo contexto TLS que a API usa
# (src.core.db.ssl_context). Argumentos: host e modo (verify-full ou disable). Sai 0 se conectou;
# se não, escreve o tipo e a mensagem do erro na saída de erro.
_CONECTAR = """
import asyncio, os, sys
import asyncpg
from sqlalchemy.engine import make_url
from src.core.config import DatabaseSslMode
from src.core.db import ssl_context

async def conectar(host, modo):
    url = make_url(os.environ["DATABASE_URL"])
    contexto = ssl_context(DatabaseSslMode(modo), os.environ["DATABASE_SSL_ROOT_CERT"])
    conexao = await asyncpg.connect(
        host=host, port=url.port or 5432, user=url.username, password=url.password,
        database=url.database, ssl=contexto, timeout=5,
    )
    await conexao.close()

try:
    asyncio.run(conectar(sys.argv[1], sys.argv[2]))
except Exception as erro:
    print(type(erro).__name__, erro, file=sys.stderr)
    sys.exit(1)
"""


type Resultado = subprocess.CompletedProcess[str]


def _rodar(*comando: str, check: bool = True, timeout: int = 120) -> Resultado:
    # Comandos fixos deste arquivo, sem entrada externa.
    return subprocess.run(  # noqa: S603
        comando, capture_output=True, text=True, check=check, timeout=timeout, cwd=RAIZ
    )


def _compose(*args: str, check: bool = True, timeout: int = 120) -> Resultado:
    assert DOCKER is not None
    return _rodar(
        DOCKER, "compose", "-f", str(COMPOSE), "-p", PROJETO, *args, check=check, timeout=timeout
    )


def _psql_local(sql: str) -> str:
    """Consulta pelo socket local do `db` (sem rede), como o healthcheck."""
    return _compose("exec", "-T", "db", "psql", "-U", "sgs", "-d", "sgs", "-AtX", "-c", sql).stdout


def _conectar_da_api(host: str, modo: str) -> Resultado:
    return _compose("exec", "-T", "api", "python", "-c", _CONECTAR, host, modo, check=False)


def _psql_tcp(sslmode: str) -> Resultado:
    """`psql` por TCP dentro do próprio `db`, com o dono do banco e o `sslmode` dado."""
    conexao = f"host=127.0.0.1 user=sgs dbname=sgs sslmode={sslmode}"
    comando = f'PGPASSWORD="$POSTGRES_PASSWORD" psql -w -AtX -c "SELECT 1" "{conexao}"'
    return _compose("exec", "-T", "db", "sh", "-c", comando, check=False)


@pytest.fixture(scope="module")
def ambiente() -> Iterator[None]:
    if DOCKER is None:
        pytest.skip("Docker não encontrado")
    # A API não sobe sem a chave JWT (spec 002); se ela não existe, o teste cria e apaga no fim.
    criou_pasta = not CHAVES_JWT.parent.exists()
    criou_chave = not CHAVES_JWT.exists()
    if criou_chave:
        CHAVES_JWT.parent.mkdir(exist_ok=True)
        jwt_keys.main(["--output", str(CHAVES_JWT)])
    try:
        subida = _compose("up", "-d", "--build", "--wait", "api", check=False, timeout=900)
        if subida.returncode != 0:
            logs = _compose("logs", "--no-color", "--tail", "100", check=False)
            pytest.fail(f"o compose não subiu:\n{subida.stderr}\n{logs.stdout}")
        yield
    finally:
        _compose("down", "-v", "--remove-orphans", check=False, timeout=300)
        if criou_chave:
            CHAVES_JWT.unlink(missing_ok=True)
        if criou_pasta:
            CHAVES_JWT.parent.rmdir()


def test_api_em_verify_full_fica_pronta_com_conexoes_cifradas(ambiente: None) -> None:
    """011/R10.3"""
    modo = _compose("exec", "-T", "api", "printenv", "DATABASE_SSL_MODE").stdout.strip()
    assert modo == "verify-full"

    pronta = _compose("exec", "-T", "api", "python", "-c", _PRONTA).stdout.strip()
    assert pronta == '200 {"status":"ok"}'

    # As conexões que a API mantém no pool estão todas em TLS 1.2 ou 1.3.
    contagem = _psql_local(
        "SELECT count(*) FILTER (WHERE s.ssl AND s.version IN ('TLSv1.2', 'TLSv1.3')),"
        " count(*) FILTER (WHERE NOT s.ssl OR s.version NOT IN ('TLSv1.2', 'TLSv1.3'))"
        " FROM pg_stat_ssl s JOIN pg_stat_activity a USING (pid) WHERE a.usename = 'sgs_api'"
    ).strip()
    cifradas, sem_tls = (int(n) for n in contagem.split("|"))
    assert cifradas > 0
    assert sem_tls == 0


def test_verify_full_confere_o_nome_do_servidor_no_certificado(ambiente: None) -> None:
    """011/R10.3"""
    pelo_nome = _conectar_da_api("db", "verify-full")
    assert pelo_nome.returncode == 0, pelo_nome.stderr

    ip = _compose(
        "exec", "-T", "api", "python", "-c", "import socket; print(socket.gethostbyname('db'))"
    ).stdout.strip()
    pelo_ip = _conectar_da_api(ip, "verify-full")
    assert pelo_ip.returncode != 0
    assert "SSLCertVerificationError" in pelo_ip.stderr


def test_banco_recusa_conexao_pela_rede_sem_tls(ambiente: None) -> None:
    """011/R10.4"""
    # Da rede do compose, a partir do container da API.
    da_api = _conectar_da_api("db", "disable")
    assert da_api.returncode != 0
    assert "no encryption" in da_api.stderr

    # Por TCP dentro do próprio servidor: sem TLS é recusado; com TLS, a mesma conta entra.
    sem_tls = _psql_tcp("disable")
    assert sem_tls.returncode != 0
    assert "no encryption" in sem_tls.stderr
    com_tls = _psql_tcp("require")
    assert com_tls.returncode == 0, com_tls.stderr


def test_certificados_sao_gerados_na_subida_sem_a_chave_da_ca(ambiente: None) -> None:
    """011/R10.5"""
    # Lista o volume inteiro, montado pelo próprio db-certs.
    comando = "find /certs -type f -exec stat -c '%n %u %a' {} +"
    listagem = _compose(
        "run", "--rm", "--no-deps", "--entrypoint", "sh", "db-certs", "-c", comando
    ).stdout
    # Só o certificado da CA vai para a API; a chave do servidor é do usuário postgres (uid 999),
    # com modo 0600; a chave da CA não fica no volume.
    assert sorted(listagem.splitlines()) == [
        "/certs/ca/ca.crt 0 644",
        "/certs/server/server.crt 0 644",
        "/certs/server/server.key 999 600",
    ]
    # O usuário da API também tem uid 999: ela só pode enxergar o certificado da CA.
    assert _compose("exec", "-T", "api", "ls", "/certs").stdout.split() == ["ca.crt"]


def test_nenhuma_chave_nem_certificado_esta_no_git() -> None:
    """011/R10.5"""
    assert GIT is not None
    rastreados = _rodar(GIT, "ls-files").stdout.splitlines()
    proibidos = [
        caminho
        for caminho in rastreados
        if caminho.startswith("secrets/") or Path(caminho).suffix.lower() in EXTENSOES_PROIBIDAS
    ]
    assert proibidos == []
