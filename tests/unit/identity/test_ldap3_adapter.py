"""Adaptador `ldap3` do diretório (spec 004, T2), com o `MOCK_SYNC` carregado de um LDIF."""

import inspect
import ssl
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import anyio
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from ldap3 import MOCK_SYNC, Connection, Server
from pydantic import SecretStr

from src.modules.identity.domain.diretorio import DirectoryUnavailable, DirectoryUser
from src.modules.identity.infrastructure.ldap3_directory import Ldap3Directory, LdapConfig

LDIF = Path(__file__).with_name("diretorio_teste.ldif")
SERVICO_DN = "cn=sgs-sync,ou=servicos,dc=teste"
SERVICO_SENHA = "senha-exemplo-servico"
ATRIBUTOS_DE_USUARIO = {"uid", "mail", "cn", "entryUUID"}


def _ler_ldif(caminho: Path) -> Iterator[tuple[str, dict[str, list[str]]]]:
    """LDIF simples (sem continuação nem base64): uma entrada por bloco."""
    for bloco in caminho.read_text(encoding="utf-8").split("\n\n"):
        linhas = [linha for linha in bloco.splitlines() if linha and not linha.startswith("#")]
        if not linhas:
            continue
        dn = linhas[0].removeprefix("dn: ")
        atributos: dict[str, list[str]] = {}
        for linha in linhas[1:]:
            nome, valor = linha.split(": ", 1)
            atributos.setdefault(nome, []).append(valor)
        yield dn, atributos


def _config(**mudancas: Any) -> LdapConfig:
    base: dict[str, Any] = {
        "url": "ldaps://ldap.teste:636",
        "start_tls": False,
        "ca_file": None,
        "bind_dn": SERVICO_DN,
        "bind_password": SecretStr(SERVICO_SENHA),
        "user_base": "ou=pessoas,dc=teste",
        "user_filter": "(objectClass=inetOrgPerson)",
        "group_base": "ou=grupos,dc=teste",
        "group_filter": "(objectClass=groupOfNames)",
        "attr_login": "uid",
        "attr_email": "mail",
        "attr_name": "cn",
        "attr_id": "entryUUID",
        "attr_member": "member",
        "page_size": 500,
    }
    return LdapConfig(**(base | mudancas))


@pytest.fixture
def servidor() -> Server:
    server = Server("ldap.teste")
    carga = Connection(server, client_strategy=MOCK_SYNC)
    for dn, atributos in _ler_ldif(LDIF):
        carga.strategy.add_entry(dn, atributos)
    return server


@pytest.fixture
def diretorio(servidor: Server) -> Ldap3Directory:
    return Ldap3Directory(_config(), server=servidor, client_strategy=MOCK_SYNC)


@pytest.fixture
def buscas(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Registra cada `Connection.search` (filtro, atributos, página e *thread*)."""
    registro: list[dict[str, Any]] = []
    original = Connection.search

    def espiao(self: Connection, *args: Any, **kwargs: Any) -> Any:
        chamada = inspect.signature(original).bind(self, *args, **kwargs).arguments
        registro.append(
            {
                "filtro": chamada["search_filter"],
                "atributos": chamada.get("attributes"),
                "pagina": chamada.get("paged_size"),
                "thread": threading.get_ident(),
            }
        )
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Connection, "search", espiao)
    return registro


async def test_snapshot_le_usuarios_e_grupos_normalizados(diretorio: Ldap3Directory) -> None:
    """004/R1.4, R1.5 (login e e-mail em minúsculas; o identificador vem de LDAP_ATTR_ID)"""
    retrato = await diretorio.snapshot()

    usuarios = {u.login: u for u in retrato.users}
    assert set(usuarios) == {"ana", "bruno", "carla", "davi", "elisa"}
    assert usuarios["ana"] == DirectoryUser(
        external_id="0b1f6a7e-0000-4000-8000-000000000001",
        dn="uid=ana,ou=pessoas,dc=teste",
        login="ana",
        email="ana.souza@recife.pe.gov.br",
        display_name="Ana Souza",
    )
    assert usuarios["bruno"].email is None
    grupos = {g.name: g for g in retrato.groups}
    assert set(grupos) == {"gestores", "analistas"}
    assert grupos["gestores"].external_id == "0b1f6a7e-0000-4000-8000-0000000000a1"
    assert grupos["gestores"].member_dns == frozenset(
        {"uid=ana,ou=pessoas,dc=teste", "uid=bruno,ou=pessoas,dc=teste"}
    )


async def test_snapshot_pagina_e_pede_so_os_atributos_configurados(
    servidor: Server, buscas: list[dict[str, Any]]
) -> None:
    """004/R1.4 (busca paginada, RFC 2696, só com os atributos configurados)"""
    diretorio = Ldap3Directory(_config(page_size=2), server=servidor, client_strategy=MOCK_SYNC)

    retrato = await diretorio.snapshot()

    assert len(retrato.users) == 5
    de_usuarios = [b for b in buscas if b["filtro"] == "(objectClass=inetOrgPerson)"]
    assert len(de_usuarios) >= 3  # 5 usuários em páginas de 2
    assert all(b["pagina"] == 2 for b in buscas)
    assert all(set(b["atributos"]) == ATRIBUTOS_DE_USUARIO for b in de_usuarios)
    de_grupos = [b for b in buscas if b["filtro"] == "(objectClass=groupOfNames)"]
    assert all(set(b["atributos"]) == {"cn", "entryUUID", "member"} for b in de_grupos)


async def test_attr_id_vazio_usa_o_dn(servidor: Server) -> None:
    """004/R1.5"""
    diretorio = Ldap3Directory(_config(attr_id=""), server=servidor, client_strategy=MOCK_SYNC)

    usuario = await diretorio.find_user("ana")

    assert usuario is not None
    assert usuario.external_id == "uid=ana,ou=pessoas,dc=teste"


async def test_find_user_acha_pelo_login_sem_diferenciar_maiusculas(
    diretorio: Ldap3Directory,
) -> None:
    """004/R2.1"""
    usuario = await diretorio.find_user("BRUNO")

    assert usuario is not None
    assert (usuario.dn, usuario.login) == ("uid=bruno,ou=pessoas,dc=teste", "bruno")
    assert await diretorio.find_user("ninguem") is None


@pytest.mark.parametrize("login", ["*", "*)(uid=*", "ana)(|(uid=*", "ana\x00", "(uid=ana)"])
async def test_find_user_escapa_o_login_no_filtro(
    diretorio: Ldap3Directory, buscas: list[dict[str, Any]], login: str
) -> None:
    """004/R2.2 (entradas maliciosas não alteram o filtro)"""
    assert await diretorio.find_user(login) is None

    filtro = buscas[-1]["filtro"]
    assert filtro.count("(") == filtro.count(")") == 3
    assert "*" not in filtro


@settings(max_examples=60, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(login=st.text(min_size=1, max_size=30))
def test_find_user_com_qualquer_texto_so_acha_o_login_exato(
    diretorio: Ldap3Directory, login: str
) -> None:
    """004/R2.2"""
    usuario = anyio.run(diretorio.find_user, login)

    assert usuario is None or usuario.login == login.lower()


async def test_verify_password_confere_por_bind_com_o_dn(diretorio: Ldap3Directory) -> None:
    """004/R2.1"""
    dn = "uid=ana,ou=pessoas,dc=teste"

    assert await diretorio.verify_password(dn, "senha-exemplo-ana") is True
    assert await diretorio.verify_password(dn, "senha-errada") is False


async def test_senha_vazia_e_recusada_sem_bind(
    diretorio: Ldap3Directory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """004/R2.4 (nenhum bind, que poderia virar bind anônimo)"""
    binds: list[str | None] = []
    original = Connection.bind

    def espiao(self: Connection, *args: Any, **kwargs: Any) -> Any:
        binds.append(self.user)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Connection, "bind", espiao)

    assert await diretorio.verify_password("uid=ana,ou=pessoas,dc=teste", "") is False
    assert binds == []


async def test_groups_of_devolve_os_grupos_do_usuario(diretorio: Ldap3Directory) -> None:
    """004/R2.3"""
    ana = await diretorio.find_user("ana")
    davi = await diretorio.find_user("davi")
    assert ana is not None
    assert davi is not None

    assert {g.name for g in await diretorio.groups_of(ana)} == {"gestores", "analistas"}
    assert await diretorio.groups_of(davi) == ()


async def test_chamadas_ao_ldap3_rodam_fora_do_loop(
    diretorio: Ldap3Directory, buscas: list[dict[str, Any]]
) -> None:
    """004/R1.4, R2.1 (design § Portas e adaptadores: o `ldap3` é síncrono e cada chamada roda
    em `anyio.to_thread.run_sync`)"""
    await diretorio.find_user("ana")

    assert buscas
    assert all(b["thread"] != threading.get_ident() for b in buscas)


async def test_falha_da_conta_de_servico_vira_indisponivel_sem_a_senha(servidor: Server) -> None:
    """004/R1.3, R1.10 (erro genérico; a senha nunca entra na exceção)"""
    senha = "senha-exemplo-errada-123"
    diretorio = Ldap3Directory(
        _config(bind_password=SecretStr(senha)), server=servidor, client_strategy=MOCK_SYNC
    )

    with pytest.raises(DirectoryUnavailable) as erro:
        await diretorio.find_user("ana")

    assert senha not in str(erro.value)
    assert senha not in repr(erro.value.args)
    assert erro.value.__cause__ is None


def test_monta_o_servidor_com_tls_conferido(tmp_path: Path) -> None:
    """004/R1.2 (LDAPS com a CA configurada e conferência do nome do servidor)"""
    ca = tmp_path / "ca.crt"
    ca.write_text("x", encoding="utf-8")

    servidor = Ldap3Directory(_config(ca_file=ca))._server

    assert (servidor.host, servidor.port, servidor.ssl) == ("ldap.teste", 636, True)
    assert servidor.tls.validate == ssl.CERT_REQUIRED
    assert servidor.tls.ca_certs_file == str(ca)
    assert servidor.tls.valid_names == ["ldap.teste"]


def test_login_e_email_sem_espacos_nas_pontas(diretorio: Ldap3Directory) -> None:
    """004/R1.5, R4.2 (o plano compara o login como `users` o guarda: sem espaços nas pontas)"""
    entrada = {
        "dn": "uid=ana,ou=pessoas,dc=teste",
        "attributes": {
            "uid": [" Ana "],
            "mail": [" Ana@Recife.pe.gov.br "],
            "cn": ["Ana"],
            "entryUUID": ["uuid-ana"],
        },
    }

    usuario = diretorio._to_user(entrada)

    assert usuario is not None
    assert (usuario.login, usuario.email) == ("ana", "ana@recife.pe.gov.br")
