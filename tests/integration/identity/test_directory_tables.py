"""Tabelas do diretório e repositórios sobre o PostgreSQL (004/T1, migração 0004_diretorio)."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from alembic import command
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.core.db import alembic_config
from src.core.ids import uuid7
from src.modules.identity.domain.espelho_diretorio import SyncConflict, SyncCounts
from src.modules.identity.domain.oidc import OidcLoginRequest
from src.modules.identity.infrastructure.directory_repository import (
    SqlDirectoryRepository,
    SqlOidcLoginRequests,
)
from src.modules.identity.infrastructure.repository import SqlUserRepository
from tests.factories import ARGON2ID_DE_TESTE, make_user
from tests.integration.postgres import BancoDeTeste, motor

AGORA = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)
HASH_A = "a" * 64
HASH_B = "b" * 64
INSERIR_MAPEAMENTO = text(
    "INSERT INTO group_role_mappings (id, group_id, role_id, scope_type, created_by)"
    " SELECT :id, :grupo, id, 'global', :admin FROM roles LIMIT 1"
)


@pytest.fixture
async def sessoes(banco: BancoDeTeste) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Sessões com o login da API (papel sgs_app), como em produção."""
    engine = motor(banco.url_api)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def _usuario(sessoes: async_sessionmaker[AsyncSession], **campos: object) -> UUID:
    usuario = make_user(**campos)
    async with sessoes() as sessao, sessao.begin():
        await SqlUserRepository(sessao).add(usuario)
    return usuario.id


async def test_upsert_de_grupo_por_origem_e_external_id(
    sessoes: async_sessionmaker[AsyncSession],
) -> None:
    """004/R1.14: o grupo espelhado é um só por (origem, external_id), com id estável."""
    async with sessoes() as sessao, sessao.begin():
        repositorio = SqlDirectoryRepository(sessao)
        criado = await repositorio.upsert_group("ldap", "cn=ti", "TI", AGORA)
        de_novo = await repositorio.upsert_group("ldap", "cn=ti", "TI renomeado", AGORA)
        outra_origem = await repositorio.upsert_group("oidc", "cn=ti", "TI", AGORA)

    assert criado.created
    assert not de_novo.created
    assert de_novo.id == criado.id
    assert outra_origem.id != criado.id
    async with sessoes() as sessao:
        nome = await sessao.scalar(
            text("SELECT name FROM groups WHERE id = :id"), {"id": criado.id}
        )
    assert nome == "TI renomeado"


async def test_grupo_recusa_origem_local(sessoes: async_sessionmaker[AsyncSession]) -> None:
    """004/R1.14: só há grupos espelhados de `ldap` e `oidc`."""
    with pytest.raises(IntegrityError, match="ck_groups_origem_valida"):
        async with sessoes() as sessao, sessao.begin():
            await SqlDirectoryRepository(sessao).upsert_group(
                "local",  # type: ignore[arg-type]  # o banco também recusa, não só o tipo
                "x",
                "X",
                AGORA,
            )


async def test_desativa_grupos_ausentes_e_reativa_no_upsert(
    sessoes: async_sessionmaker[AsyncSession],
) -> None:
    """004/R1.14: grupo que sumiu do diretório fica inativo, sem ser apagado."""
    async with sessoes() as sessao, sessao.begin():
        repositorio = SqlDirectoryRepository(sessao)
        fica = await repositorio.upsert_group("ldap", "cn=fica", "Fica", AGORA)
        sai = await repositorio.upsert_group("ldap", "cn=sai", "Sai", AGORA)
        desativados = await repositorio.deactivate_groups_except("ldap", {"cn=fica"}, AGORA)
    assert desativados == 1

    async with sessoes() as sessao:
        ativos = await sessao.execute(text("SELECT id, is_active FROM groups"))
        assert dict(ativos.all()) == {fica.id: True, sai.id: False}
    async with sessoes() as sessao, sessao.begin():
        await SqlDirectoryRepository(sessao).upsert_group("ldap", "cn=sai", "Sai", AGORA)
        assert await sessao.scalar(text("SELECT bool_and(is_active) FROM groups"))


async def test_troca_associacoes_e_conta_membros_ativos(
    sessoes: async_sessionmaker[AsyncSession],
) -> None:
    """004/R1.14: os membros ativos de cada grupo vêm de `user_groups` com `users.is_active`."""
    ativo = await _usuario(sessoes, username="ana", email="ana@recife.pe.gov.br")
    inativo = await _usuario(sessoes, username="bia", email="bia@recife.pe.gov.br", is_active=False)
    async with sessoes() as sessao, sessao.begin():
        repositorio = SqlDirectoryRepository(sessao)
        a = (await repositorio.upsert_group("ldap", "cn=a", "A", AGORA)).id
        b = (await repositorio.upsert_group("ldap", "cn=b", "B", AGORA)).id
        await repositorio.replace_user_groups(ativo, "ldap", {a, b})
        await repositorio.replace_user_groups(inativo, "ldap", {a})
        await repositorio.replace_user_groups(ativo, "ldap", {a})

        assert await repositorio.groups_of_user(ativo, "ldap") == frozenset({a})
        assert await repositorio.active_member_counts({a, b}) == {a: 1, b: 0}


async def test_uma_execucao_em_andamento_por_vez(
    sessoes: async_sessionmaker[AsyncSession],
) -> None:
    """004/R1.11: o índice único parcial recusa a segunda execução em andamento."""
    primeira, segunda, terceira = uuid7(), uuid7(), uuid7()
    async with sessoes() as sessao, sessao.begin():
        repositorio = SqlDirectoryRepository(sessao)
        assert await repositorio.start_run(primeira, triggered_by=None, agora=AGORA)
        assert not await repositorio.start_run(segunda, triggered_by=None, agora=AGORA)
        await repositorio.finish_run(primeira, "falhou", AGORA, error="Diretório indisponível")
        assert await repositorio.start_run(terceira, triggered_by=None, agora=AGORA)

    async with sessoes() as sessao:
        indice = await sessao.scalar(
            text("SELECT indexdef FROM pg_indexes WHERE indexname = :nome"),
            {"nome": "ux_directory_sync_runs_em_andamento"},
        )
    assert indice is not None
    assert "UNIQUE" in indice
    assert "em_andamento" in indice


async def test_execucao_concluida_guarda_contagens_e_conflitos(
    sessoes: async_sessionmaker[AsyncSession],
) -> None:
    """004/R1.9: a execução registra quem disparou, as contagens e os conflitos."""
    admin = await _usuario(sessoes)
    existente = await _usuario(sessoes, username="caio", email="caio@recife.pe.gov.br")
    execucao = uuid7()
    contagens = SyncCounts(users_created=2, users_updated=1, groups_created=3)
    conflito = SyncConflict(tipo="email", external_id="uuid-1", usuario_existente_id=existente)
    async with sessoes() as sessao, sessao.begin():
        repositorio = SqlDirectoryRepository(sessao)
        await repositorio.start_run(execucao, triggered_by=admin, agora=AGORA)
        fim = AGORA + timedelta(seconds=5)
        await repositorio.finish_run(
            execucao, "concluida", fim, counts=contagens, conflicts=(conflito,)
        )

    async with sessoes() as sessao:
        gravada = await SqlDirectoryRepository(sessao).get_run(execucao)
    assert gravada is not None
    assert (gravada.status, gravada.triggered_by, gravada.finished_at) == ("concluida", admin, fim)
    assert gravada.counts == contagens
    assert gravada.conflicts == (conflito,)
    assert gravada.error is None


async def test_execucao_recusa_contagem_negativa(
    sessoes: async_sessionmaker[AsyncSession],
) -> None:
    """004/R1.9: contagens são inteiros não negativos."""
    execucao = uuid7()
    async with sessoes() as sessao, sessao.begin():
        await SqlDirectoryRepository(sessao).start_run(execucao, triggered_by=None, agora=AGORA)
    negativa = SyncCounts(users_created=-1)
    with pytest.raises(IntegrityError, match="ck_directory_sync_runs_contagens_nao_negativas"):
        async with sessoes() as sessao, sessao.begin():
            await SqlDirectoryRepository(sessao).finish_run(
                execucao, "concluida", AGORA, counts=negativa
            )


async def test_mapeamento_exige_grupo_existente(
    sessoes: async_sessionmaker[AsyncSession],
) -> None:
    """004/R1.14 e 003/R3.1: `group_role_mappings.group_id` aponta um grupo de verdade."""
    admin = await _usuario(sessoes)
    with pytest.raises(IntegrityError, match="fk_group_role_mappings_group_id_groups"):
        async with sessoes() as sessao, sessao.begin():
            await sessao.execute(
                INSERIR_MAPEAMENTO, {"id": uuid7(), "grupo": uuid7(), "admin": admin}
            )


def _migrar_ate(conexao: Connection, revisao: str) -> None:
    config = alembic_config()
    config.attributes["connection"] = conexao
    command.upgrade(config, revisao)


async def test_migracao_para_se_houver_mapeamento_orfao(banco_vazio: BancoDeTeste) -> None:
    """004/R1.14: a FK só entra sem `group_id` órfão; a migração para e diz o que fazer."""
    engine = motor(banco_vazio.url_dono)
    try:
        async with engine.connect() as conexao:
            await conexao.run_sync(_migrar_ate, "0013_04")
            admin = uuid7()
            await conexao.execute(
                text(
                    "INSERT INTO users (id, username, display_name, source, password_hash)"
                    " VALUES (:id, 'admin', 'Admin', 'local', :senha)"
                ),
                {"id": admin, "senha": ARGON2ID_DE_TESTE},
            )
            await conexao.execute(
                INSERIR_MAPEAMENTO,
                {"id": uuid7(), "grupo": uuid7(), "admin": admin},
            )
            await conexao.commit()

            with pytest.raises(RuntimeError, match=r"group_role_mappings.*órfão"):
                await conexao.run_sync(_migrar_ate, "0004")
    finally:
        await engine.dispose()


async def test_state_do_oidc_e_consumido_uma_vez(
    sessoes: async_sessionmaker[AsyncSession],
) -> None:
    """004/R3.7: o `state` é de uso único; a segunda leitura não acha nada."""
    pedido = OidcLoginRequest(
        id=uuid7(),
        state_hash=HASH_A,
        binding_hash=HASH_B,
        nonce="n" * 43,
        code_verifier_enc="v1:abc:def",
        created_at=AGORA,
        expires_at=AGORA + timedelta(minutes=10),
    )
    async with sessoes() as sessao, sessao.begin():
        await SqlOidcLoginRequests(sessao).add(pedido)

    depois = AGORA + timedelta(minutes=1)
    async with sessoes() as sessao, sessao.begin():
        consumido = await SqlOidcLoginRequests(sessao).consume(HASH_A, depois)
    async with sessoes() as sessao, sessao.begin():
        repetido = await SqlOidcLoginRequests(sessao).consume(HASH_A, depois)

    assert consumido == pedido
    assert repetido is None


async def test_state_vencido_nao_e_consumido_e_a_limpeza_apaga(
    sessoes: async_sessionmaker[AsyncSession],
) -> None:
    """004/R3.7: `state` vencido é recusado; vencidos há mais de um dia são apagados."""
    vencimento = AGORA + timedelta(minutes=10)
    pedido = OidcLoginRequest(uuid7(), HASH_A, HASH_B, "n", "v1:a:b", AGORA, vencimento)
    async with sessoes() as sessao, sessao.begin():
        repositorio = SqlOidcLoginRequests(sessao)
        await repositorio.add(pedido)
        assert await repositorio.consume(HASH_A, vencimento) is None
        assert await repositorio.delete_expired_before(vencimento) == 0
        assert await repositorio.delete_expired_before(vencimento + timedelta(seconds=1)) == 1


async def test_pedido_oidc_recusa_vencimento_antes_da_criacao(
    sessoes: async_sessionmaker[AsyncSession],
) -> None:
    """004/R3.7: `expires_at` vem depois de `created_at`."""
    pedido = OidcLoginRequest(uuid7(), HASH_A, HASH_B, "n", "v1:a:b", AGORA, AGORA)
    with pytest.raises(IntegrityError, match="ck_oidc_login_requests_vence_depois_de_criar"):
        async with sessoes() as sessao, sessao.begin():
            await SqlOidcLoginRequests(sessao).add(pedido)
