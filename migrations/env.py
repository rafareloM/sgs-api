"""Ambiente do Alembic: migrações assíncronas com asyncpg (spec 001).

- Chamado por `src.core.db.run_migrations` (subida em dev e testes): recebe a conexão pronta.
- Chamado pela linha de comando (`alembic upgrade head`, `make migrate`): conecta com
  DATABASE_MIGRATION_URL (dono do banco) ou, na falta dela, DATABASE_URL.
- Modo offline (`alembic upgrade head --sql`, spec 011): imprime o DDL sem conectar nem ler a
  configuração, inclusive o dos `.sql` de `migrations/sql/` (base do `make sql-bd`).
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection, text

from src.core.config import load_settings
from src.core.db import MIGRATION_LOCK_ID, create_engine, incluir_no_autogenerate, metadata

# Registram as tabelas de cada módulo no metadata, para o autogenerate (`make migrate`) vê-las.
from src.modules.access.infrastructure import tables as _access_tables  # noqa: F401
from src.modules.audit.infrastructure import tables as _audit_tables  # noqa: F401
from src.modules.identity.infrastructure import tables as _identity_tables  # noqa: F401
from src.modules.registry.infrastructure import tables as _registry_tables  # noqa: F401

config = context.config


def _run(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=metadata,
        compare_type=True,
        include_name=incluir_no_autogenerate,
    )
    with context.begin_transaction():
        connection.execute(text("SELECT pg_advisory_xact_lock(:id)"), {"id": MIGRATION_LOCK_ID})
        context.run_migrations()


async def _run_from_command_line() -> None:
    settings = load_settings()
    url = settings.database_migration_url or settings.database_url
    engine = create_engine(url.get_secret_value(), settings, pooled=False)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(_run)
            await connection.commit()
    finally:
        await engine.dispose()


def _run_offline() -> None:
    # Só o dialeto: não conecta nem lê a configuração. O paramstyle `named` evita que o
    # dialeto padrão (psycopg2) dobre os `%` do DDL na saída.
    context.configure(
        dialect_name="postgresql",
        target_metadata=metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


_connection = config.attributes.get("connection")
if _connection is None and config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

if context.is_offline_mode():
    _run_offline()
elif _connection is not None:
    _run(_connection)
else:
    asyncio.run(_run_from_command_line())
