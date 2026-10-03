"""PostgreSQL de verdade para os testes de integração.

Usa o servidor de SGS_TEST_DATABASE_URL (no CI, o serviço postgres do workflow) ou sobe um
postgres:17 com testcontainers. As migrações rodam uma vez num banco-modelo; cada teste recebe um
banco novo copiado dele (CREATE DATABASE ... TEMPLATE), porque o audit_log não aceita limpeza.
"""

import os
import uuid
from collections.abc import AsyncIterator, Iterator

import pytest
from sqlalchemy import URL, make_url, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool
from testcontainers.community.postgres import PostgresContainer

from sgs_api.core.db import run_migrations
from tests.factories import make_settings
from tests.integration.postgres import LOGIN_DA_API, SENHA_DA_API, BancoDeTeste, como_texto

BANCO_MODELO = "sgs_modelo"


@pytest.fixture(scope="session")
def servidor_postgres() -> Iterator[URL]:
    configurado = os.environ.get("SGS_TEST_DATABASE_URL")
    if configurado:
        yield make_url(configurado)
        return
    with PostgresContainer("postgres:17", driver="asyncpg") as container:
        yield make_url(container.get_connection_url())


def _administrador(servidor: URL) -> AsyncEngine:
    """Conexão ao banco `postgres`, fora de transação (CREATE/DROP DATABASE exigem isso)."""
    return create_async_engine(
        servidor.set(database="postgres"), isolation_level="AUTOCOMMIT", poolclass=NullPool
    )


@pytest.fixture(scope="session")
async def banco_modelo(servidor_postgres: URL) -> URL:
    administrador = _administrador(servidor_postgres)
    try:
        async with administrador.connect() as conexao:
            await conexao.execute(text(f"DROP DATABASE IF EXISTS {BANCO_MODELO} WITH (FORCE)"))
            await conexao.execute(text(f"CREATE DATABASE {BANCO_MODELO}"))
        modelo = servidor_postgres.set(database=BANCO_MODELO)
        await run_migrations(como_texto(modelo), make_settings())

        async with administrador.connect() as conexao:
            existe = await conexao.scalar(
                text("SELECT 1 FROM pg_roles WHERE rolname = :nome"), {"nome": LOGIN_DA_API}
            )
            if not existe:
                criar_login = f"CREATE ROLE {LOGIN_DA_API} LOGIN PASSWORD '{SENHA_DA_API}'"
                await conexao.execute(text(f"{criar_login} IN ROLE sgs_app"))
    finally:
        await administrador.dispose()
    return modelo


async def _banco_novo(servidor: URL, modelo: str | None) -> AsyncIterator[BancoDeTeste]:
    nome = f"teste_{uuid.uuid4().hex[:16]}"
    origem = f" TEMPLATE {modelo}" if modelo else ""
    administrador = _administrador(servidor)
    async with administrador.connect() as conexao:
        await conexao.execute(text(f"CREATE DATABASE {nome}{origem}"))
    dono = servidor.set(database=nome)
    api = dono.set(username=LOGIN_DA_API, password=SENHA_DA_API)
    try:
        yield BancoDeTeste(url_dono=como_texto(dono), url_api=como_texto(api))
    finally:
        async with administrador.connect() as conexao:
            await conexao.execute(text(f"DROP DATABASE IF EXISTS {nome} WITH (FORCE)"))
        await administrador.dispose()


@pytest.fixture
async def banco(servidor_postgres: URL, banco_modelo: URL) -> AsyncIterator[BancoDeTeste]:
    """Banco já migrado, exclusivo do teste."""
    async for banco in _banco_novo(servidor_postgres, BANCO_MODELO):
        yield banco


@pytest.fixture
async def banco_vazio(servidor_postgres: URL, banco_modelo: URL) -> AsyncIterator[BancoDeTeste]:
    """Banco sem nenhuma migração (o modelo garante que o login da API já existe)."""
    async for banco in _banco_novo(servidor_postgres, None):
        yield banco
