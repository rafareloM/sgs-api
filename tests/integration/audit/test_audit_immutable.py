"""audit_log imutável no banco (spec 001, R5.2) e migração automática na subida em dev (R1.2)."""

import asyncio

import pytest
from alembic.script import ScriptDirectory
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from src.core.config import AppEnv
from src.core.db import MIGRATION_LOCK_ID, alembic_config, run_migrations
from src.main import create_app
from tests.factories import make_settings
from tests.integration.postgres import BancoDeTeste, motor

ALTERACOES = {
    "update": "UPDATE audit_log SET action = 'adulterado'",
    "delete": "DELETE FROM audit_log",
    "truncate": "TRUNCATE audit_log",
}
SEM_PRIVILEGIO = "42501"  # SQLSTATE insufficient_privilege


async def _inserir_registro(engine: AsyncEngine) -> None:
    async with engine.begin() as conexao:
        await conexao.execute(
            text(
                "INSERT INTO audit_log (occurred_at, action, prev_hash, hash)"
                " VALUES (now(), 'teste.criado', :anterior, :atual)"
            ),
            {"anterior": "0" * 64, "atual": "a" * 64},
        )


async def _acoes_registradas(engine: AsyncEngine) -> list[str]:
    async with engine.connect() as conexao:
        return list(await conexao.scalars(text("SELECT action FROM audit_log")))


@pytest.mark.parametrize("comando", ALTERACOES.values(), ids=ALTERACOES.keys())
async def test_trigger_bloqueia_alteracao_da_trilha_ate_para_o_dono(
    banco: BancoDeTeste, comando: str
) -> None:
    """001/R5.2"""
    dono = motor(banco.url_dono)
    await _inserir_registro(dono)

    with pytest.raises(DBAPIError, match="somente inserção"):
        async with dono.begin() as conexao:
            await conexao.execute(text(comando))

    assert await _acoes_registradas(dono) == ["teste.criado"]
    await dono.dispose()


@pytest.mark.parametrize("comando", ALTERACOES.values(), ids=ALTERACOES.keys())
async def test_usuario_da_api_so_insere_e_le_a_trilha(banco: BancoDeTeste, comando: str) -> None:
    """001/R5.2"""
    api = motor(banco.url_api)
    await _inserir_registro(api)

    with pytest.raises(DBAPIError) as erro:
        async with api.begin() as conexao:
            await conexao.execute(text(comando))

    assert getattr(erro.value.orig, "sqlstate", None) == SEM_PRIVILEGIO
    assert await _acoes_registradas(api) == ["teste.criado"]
    await api.dispose()


async def _versao_e_tabela(banco: BancoDeTeste) -> tuple[str | None, str | None]:
    dono = motor(banco.url_dono)
    async with dono.connect() as conexao:
        tabela = await conexao.scalar(text("SELECT to_regclass('audit_log')::text"))
        versao = None
        if await conexao.scalar(text("SELECT to_regclass('alembic_version')::text")):
            versao = await conexao.scalar(text("SELECT version_num FROM alembic_version"))
    await dono.dispose()
    return versao, tabela


async def test_subida_em_dev_aplica_as_migracoes(banco_vazio: BancoDeTeste) -> None:
    """001/R1.2"""
    settings = make_settings(
        app_env=AppEnv.DEV,
        database_url=SecretStr(banco_vazio.url_api),
        database_migration_url=SecretStr(banco_vazio.url_dono),
    )
    app = create_app(settings)

    async with app.router.lifespan_context(app):
        pass

    head = ScriptDirectory.from_config(alembic_config()).get_current_head()
    assert await _versao_e_tabela(banco_vazio) == (head, "audit_log")


async def test_subida_fora_de_dev_nao_migra(banco_vazio: BancoDeTeste) -> None:
    """001/R1.2"""
    settings = make_settings(
        app_env=AppEnv.TEST,
        database_url=SecretStr(banco_vazio.url_api),
        database_migration_url=SecretStr(banco_vazio.url_dono),
    )
    app = create_app(settings)

    async with app.router.lifespan_context(app):
        pass

    assert await _versao_e_tabela(banco_vazio) == (None, None)


async def _aguardar_espera_pelo_lock(url: str) -> None:
    """Espera até alguma sessão do banco ficar parada no lock de migração."""
    observador = motor(url).execution_options(isolation_level="AUTOCOMMIT")
    consulta = text(
        "SELECT count(*) FROM pg_stat_activity"
        " WHERE datname = current_database() AND wait_event = 'advisory'"
    )
    try:
        async with observador.connect() as conexao:
            for _ in range(200):
                if await conexao.scalar(consulta):
                    return
                await asyncio.sleep(0.05)
    finally:
        await observador.dispose()
    pytest.fail("a migração não chegou a esperar o lock")


async def test_migracao_espera_a_de_outra_instancia_terminar(banco_vazio: BancoDeTeste) -> None:
    """001/R1.2 (instâncias que sobem juntas em dev migram uma de cada vez)"""
    outra_instancia = motor(banco_vazio.url_dono)
    async with outra_instancia.connect() as conexao:
        await conexao.execute(text("SELECT pg_advisory_xact_lock(:id)"), {"id": MIGRATION_LOCK_ID})
        migracao = asyncio.create_task(run_migrations(banco_vazio.url_dono, make_settings()))

        await _aguardar_espera_pelo_lock(banco_vazio.url_dono)
        assert not migracao.done()
        await conexao.commit()  # fim da transação: o lock é liberado

    await asyncio.wait_for(migracao, timeout=60)
    await outra_instancia.dispose()
    head = ScriptDirectory.from_config(alembic_config()).get_current_head()
    assert await _versao_e_tabela(banco_vazio) == (head, "audit_log")
