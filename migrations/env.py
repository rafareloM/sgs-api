"""Ambiente do Alembic: migrações assíncronas com asyncpg (spec 001).

- Chamado por `src.core.db.run_migrations` (subida em dev e testes): recebe a conexão pronta.
- Chamado pela linha de comando (`alembic upgrade head`, `make migrate`): conecta com
  DATABASE_MIGRATION_URL (dono do banco) ou, na falta dela, DATABASE_URL.
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection, text

from src.core.config import load_settings
from src.core.db import MIGRATION_LOCK_ID, create_engine, metadata

config = context.config


def _run(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=metadata, compare_type=True)
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


if context.is_offline_mode():
    raise SystemExit("Migrações offline (--sql) não são usadas neste projeto.")

_connection = config.attributes.get("connection")
if _connection is not None:
    _run(_connection)
else:
    if config.config_file_name is not None:
        fileConfig(config.config_file_name, disable_existing_loggers=False)
    asyncio.run(_run_from_command_line())
