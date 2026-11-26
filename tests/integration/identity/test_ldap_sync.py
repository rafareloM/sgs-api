"""Caso de uso da sincronização LDAP sobre o PostgreSQL (004/T3; design § Fluxo, Sincronização).

O diretório é um `DirectoryPort` falso em memória; o banco, os repositórios e o recálculo das
derivadas da 003 são os de verdade.
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from pydantic import SecretStr
from sqlalchemy import text

from src.core.ids import uuid7
from src.main import create_app
from src.modules.access.application.mapeamentos import recalcular_derivadas_do_usuario
from src.modules.access.infrastructure.repository import (
    SqlRepositorioDeAtribuicoes,
    SqlRepositorioDeMapeamentos,
    SqlRepositorioDePermissoes,
)
from src.modules.audit.application.registrar import Ator
from src.modules.audit.infrastructure.repository import SqlAuditStore
from src.modules.identity.application.sincronizacao import (
    iniciar_sincronizacao,
    marcar_interrompidas,
    sincronizar,
)
from src.modules.identity.domain.diretorio import (
    DirectoryGroup,
    DirectorySnapshot,
    DirectoryUnavailable,
    DirectoryUser,
)
from src.modules.identity.infrastructure.repository import SqlUserRepository
from tests.factories import make_settings, make_user
from tests.integration.acesso import Sessoes, eventos
from tests.integration.identity.sincronizacao import transacoes_de
from tests.integration.postgres import BancoDeTeste

AGORA = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)
ATOR = Ator(tipo="sistema", origem="agendador")


class DiretorioFalso:
    """`DirectoryPort` em memória: devolve o retrato atual ou levanta o erro configurado."""

    def __init__(self) -> None:
        self.usuarios: list[DirectoryUser] = []
        self.grupos: list[DirectoryGroup] = []
        self.erro: Exception | None = None

    async def snapshot(self) -> DirectorySnapshot:
        if self.erro is not None:
            raise self.erro
        return DirectorySnapshot(users=tuple(self.usuarios), groups=tuple(self.grupos))

    async def find_user(self, login: str) -> DirectoryUser | None:  # pragma: no cover
        raise NotImplementedError

    async def verify_password(self, dn: str, password: str) -> bool:  # pragma: no cover
        raise NotImplementedError

    async def groups_of(
        self, user: DirectoryUser
    ) -> tuple[DirectoryGroup, ...]:  # pragma: no cover
        raise NotImplementedError


def pessoa(login: str, *, email: str | None = None, nome: str | None = None) -> DirectoryUser:
    return DirectoryUser(
        external_id=f"uuid-{login}",
        dn=f"uid={login},ou=pessoas,dc=recife",
        login=login,
        email=email if email is not None else f"{login}@recife.pe.gov.br",
        display_name=nome or login.title(),
    )


def grupo(nome: str, *membros: DirectoryUser) -> DirectoryGroup:
    return DirectoryGroup(
        external_id=f"uuid-{nome}",
        dn=f"cn={nome},ou=grupos,dc=recife",
        name=nome,
        member_dns=frozenset(m.dn for m in membros),
    )


@pytest.fixture
def diretorio() -> DiretorioFalso:
    return DiretorioFalso()


@pytest.fixture
def transacoes(sessoes: Sessoes) -> Any:
    return transacoes_de(sessoes)


async def _executar(transacoes: Any, diretorio: DiretorioFalso) -> UUID:
    execucao = uuid7()
    assert await iniciar_sincronizacao(
        execucao, triggered_by=None, transacoes=transacoes, agora=lambda: AGORA
    )
    await sincronizar(
        execucao,
        diretorio=diretorio,
        transacoes=transacoes,
        ator=ATOR,
        gerar_id=uuid7,
        agora=lambda: AGORA,
    )
    return execucao


async def _execucao(sessoes: Sessoes, execucao: UUID) -> dict[str, Any]:
    async with sessoes() as sessao:
        linha = (
            (
                await sessao.execute(
                    text("SELECT * FROM directory_sync_runs WHERE id = :id"), {"id": execucao}
                )
            )
            .mappings()
            .one()
        )
    return dict(linha)


async def _usuarios_ldap(sessoes: Sessoes) -> dict[str, dict[str, Any]]:
    async with sessoes() as sessao:
        resultado = await sessao.execute(
            text(
                "SELECT id, username, email, display_name, external_id, is_active, synced_at"
                " FROM users WHERE source = 'ldap'"
            )
        )
        return {linha["external_id"]: dict(linha) for linha in resultado.mappings()}


async def _grupos(sessoes: Sessoes) -> dict[str, dict[str, Any]]:
    async with sessoes() as sessao:
        resultado = await sessao.execute(
            text("SELECT id, external_id, name, is_active FROM groups WHERE source = 'ldap'")
        )
        return {linha["external_id"]: dict(linha) for linha in resultado.mappings()}


async def _membros(sessoes: Sessoes) -> set[tuple[str, str]]:
    async with sessoes() as sessao:
        resultado = await sessao.execute(
            text(
                "SELECT u.external_id AS usuario, g.external_id AS grupo FROM user_groups ug"
                " JOIN users u ON u.id = ug.user_id JOIN groups g ON g.id = ug.group_id"
                " WHERE ug.source = 'ldap'"
            )
        )
        return {(linha.usuario, linha.grupo) for linha in resultado}


async def _contagens(sessoes: Sessoes) -> tuple[int, ...]:
    async with sessoes() as sessao:
        linha = (
            await sessao.execute(
                text(
                    "SELECT (SELECT count(*) FROM users), (SELECT count(*) FROM groups),"
                    " (SELECT count(*) FROM user_groups), (SELECT count(*) FROM role_assignments)"
                )
            )
        ).one()
    return tuple(linha)


async def _resultados(sessoes: Sessoes, acao: str) -> list[dict[str, Any]]:
    async with sessoes() as sessao:
        resultado = await sessao.execute(
            text(
                "SELECT actor_type, origin, entity_type, entity_id, result, result_reason, metadata"
                " FROM audit_log WHERE action = :acao ORDER BY id"
            ),
            {"acao": acao},
        )
        return [dict(linha) for linha in resultado.mappings()]


async def _mapear_auditor(sessoes: Sessoes, external_id: str) -> None:
    """Mapeamento do grupo para AUDITOR global, gravado direto (a rota é da 003/T8)."""
    admin = make_user(username=f"admin{uuid7().hex}", email=None)
    async with sessoes() as sessao, sessao.begin():
        await SqlUserRepository(sessao).add(admin)
        await sessao.execute(
            text(
                "INSERT INTO group_role_mappings (id, group_id, role_id, scope_type, created_by)"
                " SELECT :id, g.id, r.id, 'global', :admin FROM groups g, roles r"
                " WHERE g.external_id = :grupo AND r.code = 'AUDITOR'"
            ),
            {"id": uuid7(), "grupo": external_id, "admin": admin.id},
        )


async def _papeis_derivados(sessoes: Sessoes, usuario: UUID) -> list[str]:
    async with sessoes() as sessao:
        resultado = await sessao.scalars(
            text(
                "SELECT r.code FROM role_assignments ra JOIN roles r ON r.id = ra.role_id"
                " WHERE ra.user_id = :usuario AND ra.origin = 'group'"
            ),
            {"usuario": usuario},
        )
        return list(resultado)


async def test_primeira_sincronizacao_cria_usuarios_grupos_e_associacoes(
    sessoes: Sessoes, transacoes: Any, diretorio: DiretorioFalso
) -> None:
    """004/R1.5, R1.8, R1.9"""
    ana, bruno = pessoa("ana"), pessoa("bruno", email="Bruno@Recife.pe.gov.br".lower())
    diretorio.usuarios = [ana, bruno]
    diretorio.grupos = [grupo("vigilancia", ana), grupo("ti", ana, bruno)]

    execucao = await _executar(transacoes, diretorio)

    usuarios = await _usuarios_ldap(sessoes)
    assert set(usuarios) == {"uuid-ana", "uuid-bruno"}
    assert usuarios["uuid-ana"]["username"] == "ana"
    assert usuarios["uuid-ana"]["email"] == "ana@recife.pe.gov.br"
    assert usuarios["uuid-ana"]["is_active"] is True
    assert usuarios["uuid-ana"]["synced_at"] == AGORA
    assert {g["name"] for g in (await _grupos(sessoes)).values()} == {"vigilancia", "ti"}
    assert await _membros(sessoes) == {
        ("uuid-ana", "uuid-vigilancia"),
        ("uuid-ana", "uuid-ti"),
        ("uuid-bruno", "uuid-ti"),
    }

    run = await _execucao(sessoes, execucao)
    assert (run["status"], run["finished_at"], run["error"]) == ("concluida", AGORA, None)
    assert (run["users_created"], run["users_updated"], run["users_deactivated"]) == (2, 0, 0)
    assert (run["groups_created"], run["groups_updated"], run["groups_deactivated"]) == (2, 0, 0)
    assert run["conflicts"] == []

    [evento] = await _resultados(sessoes, "diretorio.sincronizado")
    assert (evento["actor_type"], evento["origin"]) == ("sistema", "agendador")
    assert (evento["entity_type"], evento["entity_id"]) == ("execucao_diretorio", str(execucao))
    assert (evento["result"], evento["result_reason"]) == ("success", None)
    assert evento["metadata"]["usuarios"] == {"criados": 2, "atualizados": 0, "desativados": 0}
    assert evento["metadata"]["conflitos"] == 0


async def test_sincronizacao_atualiza_desativa_e_reativa_sem_apagar(
    sessoes: Sessoes, transacoes: Any, diretorio: DiretorioFalso
) -> None:
    """004/R1.6, R1.7, R1.8 (status = aparecer na busca, D004-10)"""
    ana, bruno = pessoa("ana"), pessoa("bruno")
    diretorio.usuarios = [ana, bruno]
    diretorio.grupos = [grupo("ti", ana, bruno), grupo("antigo", bruno)]
    await _executar(transacoes, diretorio)

    ana_nova = pessoa("ana", email="ana.souza@recife.pe.gov.br", nome="Ana Souza")
    diretorio.usuarios = [ana_nova]
    diretorio.grupos = [grupo("ti", ana_nova)]
    segunda = await _executar(transacoes, diretorio)

    usuarios = await _usuarios_ldap(sessoes)
    assert usuarios["uuid-ana"]["display_name"] == "Ana Souza"
    assert usuarios["uuid-ana"]["email"] == "ana.souza@recife.pe.gov.br"
    assert usuarios["uuid-bruno"]["is_active"] is False  # desativado, não apagado
    grupos = await _grupos(sessoes)
    assert grupos["uuid-antigo"]["is_active"] is False
    assert await _membros(sessoes) == {("uuid-ana", "uuid-ti")}
    run = await _execucao(sessoes, segunda)
    assert (run["users_created"], run["users_updated"], run["users_deactivated"]) == (0, 1, 1)
    assert (run["groups_created"], run["groups_updated"], run["groups_deactivated"]) == (0, 1, 1)

    diretorio.usuarios = [ana_nova, bruno]
    await _executar(transacoes, diretorio)
    assert (await _usuarios_ldap(sessoes))["uuid-bruno"]["is_active"] is True


async def test_mudanca_de_grupo_recalcula_as_derivadas_da_003(
    sessoes: Sessoes, transacoes: Any, diretorio: DiretorioFalso
) -> None:
    """004/R1.8; 003/R3.2 (entrar e sair do grupo mapeado; desativado perde a derivada)"""
    ana, bruno = pessoa("ana"), pessoa("bruno")
    diretorio.usuarios = [ana, bruno]
    diretorio.grupos = [grupo("auditoria")]
    await _executar(transacoes, diretorio)
    await _mapear_auditor(sessoes, "uuid-auditoria")
    usuarios = await _usuarios_ldap(sessoes)
    id_ana, id_bruno = usuarios["uuid-ana"]["id"], usuarios["uuid-bruno"]["id"]

    diretorio.grupos = [grupo("auditoria", ana, bruno)]
    await _executar(transacoes, diretorio)
    assert await _papeis_derivados(sessoes, id_ana) == ["AUDITOR"]
    assert await _papeis_derivados(sessoes, id_bruno) == ["AUDITOR"]

    diretorio.usuarios = [ana]
    diretorio.grupos = [grupo("auditoria")]
    await _executar(transacoes, diretorio)
    assert await _papeis_derivados(sessoes, id_ana) == []
    assert await _papeis_derivados(sessoes, id_bruno) == []
    removidos = await eventos(sessoes, "papel.removido")
    assert {e["entity_id"] for e in removidos} == {str(id_ana), str(id_bruno)}


async def test_conflito_de_email_ou_username_nao_cria_nem_une_e_os_demais_seguem(
    sessoes: Sessoes, transacoes: Any, diretorio: DiretorioFalso
) -> None:
    """004/R4.2, D004-11"""
    local = make_user(username="carla", email="carla@recife.pe.gov.br")
    outro = make_user(username="dora.local", email="dora@recife.pe.gov.br")
    async with sessoes() as sessao, sessao.begin():
        await SqlUserRepository(sessao).add(local)
        await SqlUserRepository(sessao).add(outro)
    diretorio.usuarios = [
        pessoa("carla", email="c@recife.pe.gov.br"),
        pessoa("dora"),
        pessoa("eva"),
    ]

    execucao = await _executar(transacoes, diretorio)

    assert set(await _usuarios_ldap(sessoes)) == {"uuid-eva"}
    run = await _execucao(sessoes, execucao)
    assert run["status"] == "concluida"
    assert run["users_created"] == 1
    assert sorted(run["conflicts"], key=lambda c: c["tipo"]) == [
        {"tipo": "email", "external_id": "uuid-dora", "usuario_existente_id": str(outro.id)},
        {"tipo": "username", "external_id": "uuid-carla", "usuario_existente_id": str(local.id)},
    ]
    conflitos = await _resultados(sessoes, "diretorio.conflito")
    assert len(conflitos) == 2
    for evento in conflitos:
        assert (evento["result"], evento["result_reason"]) == ("denied", "conflito")
        assert evento["metadata"]["execucao_id"] == str(execucao)
        assert "email" not in evento["metadata"]  # LGPD: só ids
    [sincronizado] = await _resultados(sessoes, "diretorio.sincronizado")
    assert sincronizado["metadata"]["conflitos"] == 2


async def test_diretorio_fora_marca_falhou_sem_tocar_em_dado_local(
    sessoes: Sessoes, transacoes: Any, diretorio: DiretorioFalso
) -> None:
    """004/R1.10, R1.13 (TLS recusado chega como DirectoryUnavailable)"""
    ana = pessoa("ana")
    diretorio.usuarios = [ana]
    diretorio.grupos = [grupo("ti", ana)]
    await _executar(transacoes, diretorio)
    antes = await _contagens(sessoes)
    diretorio.erro = DirectoryUnavailable("Serviço de diretório indisponível")

    execucao = await _executar(transacoes, diretorio)

    assert await _contagens(sessoes) == antes
    assert (await _usuarios_ldap(sessoes))["uuid-ana"]["is_active"] is True
    run = await _execucao(sessoes, execucao)
    assert (run["status"], run["error"], run["finished_at"]) == (
        "falhou",
        "Diretório indisponível",
        AGORA,
    )
    falha = (await _resultados(sessoes, "diretorio.sincronizado"))[-1]
    assert (falha["result"], falha["result_reason"]) == ("failure", "erro_interno")
    assert falha["metadata"]["erro"] == "Diretório indisponível"


async def test_erro_no_meio_da_aplicacao_desfaz_tudo_e_grava_mensagem_generica(
    sessoes: Sessoes, transacoes: Any, diretorio: DiretorioFalso
) -> None:
    """004/R1.10 (transação B desfeita; o `falhou` vai numa transação própria)"""
    antes = await _contagens(sessoes)
    # O grupo é gravado antes dos usuários; o e-mail inválido de "zeca" falha depois dele.
    zeca = pessoa("zeca", email="sem-arroba")
    diretorio.usuarios = [pessoa("ana"), zeca]
    diretorio.grupos = [grupo("ti", zeca)]

    execucao = await _executar(transacoes, diretorio)

    assert await _contagens(sessoes) == antes
    run = await _execucao(sessoes, execucao)
    assert (run["status"], run["error"]) == ("falhou", "Falha na sincronização")
    assert "sem-arroba" not in str(await _resultados(sessoes, "diretorio.sincronizado"))


async def test_uma_execucao_por_vez(sessoes: Sessoes, transacoes: Any) -> None:
    """004/R1.11"""
    assert await iniciar_sincronizacao(
        uuid7(), triggered_by=None, transacoes=transacoes, agora=lambda: AGORA
    )
    assert not await iniciar_sincronizacao(
        uuid7(), triggered_by=None, transacoes=transacoes, agora=lambda: AGORA
    )


async def test_subida_marca_execucoes_interrompidas(sessoes: Sessoes, transacoes: Any) -> None:
    """004/R1.9, R1.11 (design § Fluxo, passo 6: em andamento na subida vira `falhou`)"""
    execucao = uuid7()
    await iniciar_sincronizacao(
        execucao, triggered_by=None, transacoes=transacoes, agora=lambda: AGORA
    )

    assert await marcar_interrompidas(transacoes=transacoes, agora=lambda: AGORA) == 1

    run = await _execucao(sessoes, execucao)
    assert (run["status"], run["error"]) == ("falhou", "Interrompida")
    [evento] = await _resultados(sessoes, "diretorio.sincronizado")
    assert (evento["actor_type"], evento["result"]) == ("sistema", "failure")
    assert await iniciar_sincronizacao(
        uuid7(), triggered_by=None, transacoes=transacoes, agora=lambda: AGORA
    )


async def test_lifespan_com_ldap_marca_as_interrompidas(
    banco: BancoDeTeste, sessoes: Sessoes, transacoes: Any, tmp_path: Path
) -> None:
    """004/R1.11 (design § Fluxo, passo 6: a subida da API fecha o que ficou em andamento)"""
    execucao = uuid7()
    await iniciar_sincronizacao(
        execucao, triggered_by=None, transacoes=transacoes, agora=lambda: AGORA
    )
    ca = tmp_path / "ca.crt"
    ca.write_text("-----BEGIN CERTIFICATE-----\n", encoding="utf-8")
    app = create_app(
        make_settings(
            database_url=SecretStr(banco.url_api),
            ldap_url="ldaps://ldap:636",
            ldap_ca_file=str(ca),
            ldap_bind_dn="cn=sgs-sync,dc=recife",
            ldap_bind_password=SecretStr("senha-de-teste"),
            ldap_user_base="ou=pessoas,dc=recife",
            ldap_user_filter="(objectClass=inetOrgPerson)",
            ldap_group_base="ou=grupos,dc=recife",
            ldap_group_filter="(objectClass=groupOfNames)",
        )
    )

    async with app.router.lifespan_context(app):
        run = await _execucao(sessoes, execucao)

    assert (run["status"], run["error"]) == ("falhou", "Interrompida")


async def test_falha_ao_gravar_o_falhou_nao_escapa_da_tarefa(diretorio: DiretorioFalso) -> None:
    """004/R1.10 (a tarefa em segundo plano não morre com exceção; o que ficar em andamento a
    subida fecha, passo 6)"""

    class _BancoFora:
        async def __aenter__(self) -> Any:
            raise ConnectionError("banco fora")

        async def __aexit__(self, *_: object) -> None:  # pragma: no cover
            return None

    def banco_fora() -> _BancoFora:
        return _BancoFora()

    diretorio.erro = DirectoryUnavailable("Serviço de diretório indisponível")

    await sincronizar(
        uuid7(),
        diretorio=diretorio,
        transacoes=banco_fora,
        ator=ATOR,
        gerar_id=uuid7,
        agora=lambda: AGORA,
    )


async def test_recalculo_mantem_as_derivadas_de_grupos_oidc(
    sessoes: Sessoes, transacoes: Any, diretorio: DiretorioFalso
) -> None:
    """004/R1.8; 003/R3.2 (o recálculo recebe todos os grupos do usuário, de todas as origens)"""
    ana = pessoa("ana")
    diretorio.usuarios = [ana]
    await _executar(transacoes, diretorio)
    id_ana = (await _usuarios_ldap(sessoes))["uuid-ana"]["id"]
    admin = make_user(username=f"admin{uuid7().hex}", email=None)
    async with sessoes() as sessao, sessao.begin():
        await SqlUserRepository(sessao).add(admin)
        await sessao.execute(
            text(
                "INSERT INTO groups (id, source, external_id, name)"
                " VALUES (:id, 'oidc', 'sgs-auditores', 'sgs-auditores')"
            ),
            {"id": (grupo_oidc := uuid7())},
        )
        await sessao.execute(
            text("INSERT INTO user_groups (user_id, group_id, source) VALUES (:u, :g, 'oidc')"),
            {"u": id_ana, "g": grupo_oidc},
        )
    await _mapear_auditor(sessoes, "sgs-auditores")
    async with sessoes() as sessao, sessao.begin():
        await recalcular_derivadas_do_usuario(
            id_ana,
            frozenset({grupo_oidc}),
            ator=ATOR,
            mapeamentos=SqlRepositorioDeMapeamentos(sessao),
            atribuicoes=SqlRepositorioDeAtribuicoes(sessao),
            permissoes=SqlRepositorioDePermissoes(sessao),
            auditoria=SqlAuditStore(sessao),
            gerar_id=uuid7,
        )
    assert await _papeis_derivados(sessoes, id_ana) == ["AUDITOR"]

    diretorio.grupos = [grupo("ti", ana)]  # muda os grupos LDAP: a ana é recalculada
    await _executar(transacoes, diretorio)

    assert await _papeis_derivados(sessoes, id_ana) == ["AUDITOR"]


async def test_retrato_sem_usuarios_com_contas_ldap_ativas_falha_sem_desativar(
    sessoes: Sessoes, transacoes: Any, diretorio: DiretorioFalso
) -> None:
    """004/R1.7, R1.10 (revisão da frente A, S5: um filtro ou base errados devolveriam um
    retrato vazio, e a R1.7 desativaria todas as contas LDAP)"""
    ana = pessoa("ana")
    diretorio.usuarios = [ana]
    diretorio.grupos = [grupo("ti", ana)]
    await _executar(transacoes, diretorio)
    antes = await _contagens(sessoes)
    diretorio.usuarios, diretorio.grupos = [], []

    execucao = await _executar(transacoes, diretorio)

    assert await _contagens(sessoes) == antes
    assert (await _usuarios_ldap(sessoes))["uuid-ana"]["is_active"] is True
    run = await _execucao(sessoes, execucao)
    assert (run["status"], run["error"]) == (
        "falhou",
        "Diretório sem usuários; nada foi desativado",
    )
