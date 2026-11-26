"""Servidor LDAP de laboratório (spec 004, T13; R5.1; design § `slapd`).

Sobe só o `ldap` do docker/compose.yml (com o `servicos-certs`) num projeto próprio
(`sgs-api-e2e-ldap`), com subnet de borda própria (`tests/e2e/redes.py`), e derruba só esse
projeto, com os volumes dele, no fim. Os comandos usam os `ldap-utils` de dentro do contêiner
`ldap`, pela rede `integracoes`: o compose não publica porta LDAP no host. Confere:

- a busca da conta de serviço por LDAPS, com o certificado conferido pela CA de laboratório;
- nenhuma porta LDAP em texto claro: só a 636 escuta, e nada é publicado no host;
- a escrita recusada para a conta de serviço, que também não lê as senhas;
- a carga inicial: um usuário por papel da 003, um a mais para a desativação, grupos
  `groupOfNames` com papel e escopo no nome, senhas em `{SSHA}`;
- o *alias* `ldap-nome-errado`, que chega ao mesmo servidor por um nome fora do certificado.

Fica fora do `make check`; rodar à parte com `uv run pytest tests/e2e/test_lab_ldap.py -m slow`.
"""

import base64
import os
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.e2e.redes import Borda, SubnetOcupadaError, borda_da_suite

pytestmark = pytest.mark.slow

RAIZ = Path(__file__).resolve().parents[2]
COMPOSE = RAIZ / "docker" / "compose.yml"
COMPOSE_TESTE = RAIZ / "docker" / "compose.test.yml"
PROJETO = "sgs-api-e2e-ldap"
# Lidos por tests/architecture/test_compose_configuracao.py: a API tem de aceitar esta configuração.
ARQUIVOS_COMPOSE = (COMPOSE, COMPOSE_TESTE)
AMBIENTE_COMPOSE: dict[str, str] = {}
DOCKER = shutil.which("docker")

# docker/ldap/seed.ldif
BASE = "dc=recife,dc=pe,dc=gov,dc=br"
PESSOAS = f"ou=pessoas,{BASE}"
GRUPOS = f"ou=grupos,{BASE}"
CONTA = f"cn=sgs-sync,ou=servicos,{BASE}"
SENHA_DA_CONTA = "sgs-lab-exemplo-bind"
SENHA = "sgs-lab-exemplo-usuario"
# A CA de laboratório do `servicos-certs`, montada no `ldap` só para os clientes de dentro dele.
CA = "/certs-servicos/ca.crt"
LDAPS = "ldaps://ldap:636"

USUARIOS = {
    "ldap.admin.ti",
    "ldap.gestor.dados",
    "ldap.coord.tecnico",
    "ldap.tecnico.ds3",
    "ldap.gestor.unidade",
    "ldap.diretoria",
    "ldap.auditor",
    "ldap.temporario",  # o da demonstração da desativação
}
MEMBROS = {
    "sgs-admin-ti": {"ldap.admin.ti"},
    "sgs-gestor-dados": {"ldap.gestor.dados"},
    "sgs-coord-tecnico-aps": {"ldap.coord.tecnico"},
    "sgs-tecnico-ds3": {"ldap.tecnico.ds3", "ldap.temporario"},
    "sgs-gestor-unidade-cnes-1000003": {"ldap.gestor.unidade"},
    "sgs-diretoria": {"ldap.diretoria"},
    "sgs-auditor": {"ldap.auditor"},
}

type Resultado = subprocess.CompletedProcess[str]
type Entrada = dict[str, list[str]]

_BORDA: list[Borda] = []


def _docker(
    *args: str, check: bool = True, timeout: int = 120, entrada: str | None = None
) -> Resultado:
    assert DOCKER is not None
    # Comandos fixos deste arquivo, sem entrada externa.
    return subprocess.run(  # noqa: S603
        [DOCKER, *args],
        input=entrada,
        capture_output=True,
        text=True,
        check=check,
        timeout=timeout,
        cwd=RAIZ,
        env=os.environ | AMBIENTE_COMPOSE | _BORDA[0].ambiente(),
    )


def _compose(
    *args: str, check: bool = True, timeout: int = 120, entrada: str | None = None
) -> Resultado:
    arquivos = [*(a for f in ARQUIVOS_COMPOSE for a in ("-f", str(f))), "-p", PROJETO]
    return _docker("compose", *arquivos, *args, check=check, timeout=timeout, entrada=entrada)


def _no_ldap(
    *comando: str, ambiente: dict[str, str] | None = None, entrada: str | None = None
) -> Resultado:
    """Roda no contêiner `ldap`, como o usuário dele; o código de saída fica com o teste."""
    variaveis: list[str] = []
    for nome, valor in (ambiente or {}).items():
        variaveis += ["-e", f"{nome}={valor}"]
    return _compose("exec", "-T", *variaveis, "ldap", *comando, check=False, entrada=entrada)


def _tls(*, ca: str = CA, exigir: str = "demand") -> dict[str, str]:
    """Cliente OpenLDAP conferindo o certificado, e o nome nele, pela CA dada."""
    return {"LDAPTLS_CACERT": ca, "LDAPTLS_REQCERT": exigir}


def _busca_da_conta(base: str, filtro: str, *atributos: str) -> Resultado:
    return _no_ldap(
        "ldapsearch", "-LLL", "-o", "ldif-wrap=no", "-x", "-H", LDAPS,
        "-D", CONTA, "-w", SENHA_DA_CONTA, "-b", base, filtro, *atributos,
        ambiente=_tls(),
    )  # fmt: skip


def _entradas(ldif: str) -> list[Entrada]:
    """Entradas de uma saída `ldapsearch -LLL -o ldif-wrap=no`; valores `::` decodificados."""
    entradas: list[Entrada] = []
    for bloco in ldif.strip().split("\n\n"):
        entrada: Entrada = {}
        for linha in bloco.splitlines():
            nome, _, valor = linha.partition(":")
            if valor.startswith(":"):
                valor = base64.b64decode(valor[1:].strip()).decode()
            entrada.setdefault(nome.lower(), []).append(valor.strip())
        if entrada:
            entradas.append(entrada)
    return entradas


@pytest.fixture(scope="module", autouse=True)
def laboratorio() -> Iterator[None]:
    if DOCKER is None:
        pytest.skip("Docker não encontrado")
    try:
        _BORDA[:] = [borda_da_suite("LDAP", DOCKER, projeto=PROJETO)]
    except SubnetOcupadaError as erro:
        pytest.skip(str(erro))
    try:
        subida = _compose("up", "-d", "--build", "--wait", "ldap", check=False, timeout=900)
        if subida.returncode != 0:
            logs = _compose("logs", "--no-color", "--tail", "100", check=False)
            pytest.fail(f"o compose não subiu:\n{subida.stderr}\n{logs.stdout}")
        yield
    finally:
        # Só o projeto descartável deste arquivo, pelo nome, com os volumes dele.
        _compose("down", "-v", "--remove-orphans", check=False, timeout=300)


def test_conta_de_servico_busca_por_ldaps_com_a_ca_de_laboratorio() -> None:
    """004/R5.1: a conta de serviço lê as pessoas por LDAPS, e o cliente confere o certificado do
    `ldap` pela CA de laboratório do `servicos-certs`."""
    pessoas = _busca_da_conta(PESSOAS, "(objectClass=inetOrgPerson)", "uid", "entryUUID")
    assert pessoas.returncode == 0, pessoas.stderr
    entradas = _entradas(pessoas.stdout)
    assert {e["uid"][0] for e in entradas} == USUARIOS
    # entryUUID é o LDAP_ATTR_ID do laboratório (design § Configuração).
    assert all(len(e["entryuuid"][0]) == 36 for e in entradas)

    # Confiando só no próprio certificado do servidor, e não na CA, a mesma busca não conecta.
    sem_a_ca = _no_ldap(
        "ldapsearch", "-x", "-H", LDAPS, "-D", CONTA, "-w", SENHA_DA_CONTA,
        "-b", PESSOAS, "(uid=ldap.auditor)",
        ambiente=_tls(ca="/certs/server.crt"),
    )  # fmt: skip
    assert sem_a_ca.returncode != 0
    assert "Can't contact LDAP server" in sem_a_ca.stderr


def test_sem_porta_ldap_em_texto_claro() -> None:
    """004/R5.1: só LDAPS pela rede. Nenhum socket TCP além da 636 escuta, o `ldap://` não
    conecta e nada é publicado no host."""
    escutando = _no_ldap("sh", "-c", "cat /proc/net/tcp /proc/net/tcp6 2>/dev/null")
    locais = [
        colunas[1].rsplit(":", 1)
        for linha in escutando.stdout.splitlines()
        if len(colunas := linha.split()) > 3 and colunas[3] == "0A"  # TCP_LISTEN
    ]
    # Tirando o DNS embutido do Docker (127.0.0.11, em hexadecimal invertido), que escuta numa
    # porta aleatória em todo contêiner de rede definida pelo usuário.
    portas = {int(porta, 16) for endereco, porta in locais if endereco != "0B00007F"}
    assert portas == {636}

    texto_claro = _no_ldap("ldapsearch", "-x", "-H", "ldap://ldap:389", "-b", "", "-s", "base")
    assert texto_claro.returncode != 0
    assert "Can't contact LDAP server" in texto_claro.stderr

    conteiner = _compose("ps", "-q", "ldap").stdout.strip()
    publicadas = _docker("inspect", "-f", "{{json .HostConfig.PortBindings}}", conteiner).stdout
    assert publicadas.strip() in {"{}", "null"}


def test_conta_de_servico_nao_escreve_nem_le_senhas() -> None:
    """004/R5.1 (design § `slapd`: conta de serviço só leitura por ACL): a conta não altera o
    diretório e não vê `userPassword`."""
    alteracao = f"dn: uid=ldap.auditor,{PESSOAS}\nchangetype: modify\nreplace: mail\nmail: x@x\n"
    escrita = _no_ldap(
        "ldapmodify", "-x", "-H", LDAPS, "-D", CONTA, "-w", SENHA_DA_CONTA,
        ambiente=_tls(), entrada=alteracao,
    )  # fmt: skip
    assert escrita.returncode == 50, escrita.stderr  # LDAP_INSUFFICIENT_ACCESS
    assert "Insufficient access" in escrita.stderr

    lida = _busca_da_conta(PESSOAS, "(uid=ldap.auditor)", "mail", "userPassword")
    assert lida.returncode == 0, lida.stderr
    [auditor] = _entradas(lida.stdout)
    assert auditor["mail"] == ["ldap.auditor@ldap.lab.example.org"]
    assert "userpassword" not in auditor


def test_carga_inicial_tem_os_papeis_da_003_em_grupos_groupofnames() -> None:
    """004/R5.1 (design § `slapd`): grupos `groupOfNames` com papel e escopo no nome, um usuário
    por papel da 003 e um a mais, no grupo de um técnico, para a demonstração da desativação."""
    busca = _busca_da_conta(GRUPOS, "(objectClass=groupOfNames)", "cn", "member")
    assert busca.returncode == 0, busca.stderr
    grupos = _entradas(busca.stdout)
    membros = {
        g["cn"][0]: {dn.removesuffix(f",{PESSOAS}").removeprefix("uid=") for dn in g["member"]}
        for g in grupos
    }
    assert membros == MEMBROS
    assert all(dn.endswith(f",{PESSOAS}") for g in grupos for dn in g["member"])


def test_senhas_em_ssha_e_bind_dos_usuarios_por_ldaps() -> None:
    """004/R5.1 (design § `slapd`; D004-15): as senhas fixas do laboratório ficam em `{SSHA}` e
    valem no *bind* por LDAPS, que é o que o login por LDAP (R2) faz."""
    # Pelo `ldapi`, como o usuário do contêiner: o mesmo caminho das alterações do roteiro.
    senhas = _no_ldap(
        "ldapsearch", "-LLL", "-o", "ldif-wrap=no", "-Q", "-Y", "EXTERNAL", "-H", "ldapi:///",
        "-b", BASE, "(userPassword=*)", "userPassword",
    )  # fmt: skip
    assert senhas.returncode == 0, senhas.stderr
    entradas = _entradas(senhas.stdout)
    assert {e["dn"][0] for e in entradas} == {CONTA} | {f"uid={u},{PESSOAS}" for u in USUARIOS}
    assert all(e["userpassword"][0].startswith("{SSHA}") for e in entradas)

    def quem_sou(senha: str) -> Resultado:
        return _no_ldap(
            "ldapwhoami", "-x", "-H", LDAPS, "-D", f"uid=ldap.auditor,{PESSOAS}", "-w", senha,
            ambiente=_tls(),
        )  # fmt: skip

    certa = quem_sou(SENHA)
    assert certa.returncode == 0, certa.stderr
    assert certa.stdout.strip() == f"dn:uid=ldap.auditor,{PESSOAS}"
    assert quem_sou("errada").returncode == 49  # LDAP_INVALID_CREDENTIALS


def test_alias_ldap_nome_errado_chega_ao_servidor_fora_do_certificado() -> None:
    """004 design § `slapd` (alias para o teste da R1.13): o mesmo servidor responde por
    `ldap-nome-errado`, mas o certificado só vale para `ldap`, e a conferência do nome recusa."""
    url = "ldaps://ldap-nome-errado:636"
    raiz = ["ldapsearch", "-LLL", "-x", "-H", url, "-b", "", "-s", "base", "namingContexts"]

    recusada = _no_ldap(*raiz, ambiente=_tls())
    assert recusada.returncode != 0
    assert "Can't contact LDAP server" in recusada.stderr

    sem_conferir = _no_ldap(*raiz, ambiente=_tls(exigir="never"))
    assert sem_conferir.returncode == 0, sem_conferir.stderr
    assert f"namingContexts: {BASE}" in sem_conferir.stdout
