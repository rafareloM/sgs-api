"""PostgreSQL com SQLAlchemy assíncrono e asyncpg; migrações com Alembic (spec 001)."""

import ssl
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, MetaData
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from sgs_api.core.config import DatabaseSslMode, Settings

# src/sgs_api/core/db.py → raiz do repositório, onde ficam alembic.ini e migrations/.
PROJECT_ROOT = Path(__file__).resolve().parents[3]

# Lock de sessão do PostgreSQL (pg_advisory_xact_lock) que serializa as migrações: instâncias
# que sobem juntas migram uma de cada vez. Número fixo e arbitrário.
MIGRATION_LOCK_ID = 2026_100_301

# Nomes estáveis para constraints e índices, para as migrações geradas não oscilarem.
metadata = MetaData(
    naming_convention={
        "ix": "ix_%(table_name)s_%(column_0_N_name)s",
        "uq": "uq_%(table_name)s_%(column_0_N_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }
)


def ssl_context(mode: DatabaseSslMode, root_cert: Path | None) -> ssl.SSLContext | bool:
    """Contexto TLS para o asyncpg, com a mesma semântica dos modos do libpq; TLS 1.2 no mínimo."""
    if mode is DatabaseSslMode.DISABLE:
        return False
    context = ssl.create_default_context(cafile=str(root_cert) if root_cert else None)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    if mode is DatabaseSslMode.REQUIRE:
        # Cifra sem verificar o certificado, como sslmode=require. Em prod só vale verify-full.
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    return context


def create_engine(url: str, settings: Settings, *, pooled: bool = True) -> AsyncEngine:
    connect_args = {"ssl": ssl_context(settings.database_ssl_mode, settings.database_ssl_root_cert)}
    if not pooled:
        return create_async_engine(url, poolclass=NullPool, connect_args=connect_args)
    return create_async_engine(
        url,
        pool_pre_ping=True,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        connect_args=connect_args,
    )


def alembic_config() -> Config:
    return Config(str(PROJECT_ROOT / "alembic.ini"))


async def run_migrations(url: str, settings: Settings) -> None:
    """Leva o banco até a última migração. O env.py serializa execuções simultâneas com um lock."""
    engine = create_engine(url, settings, pooled=False)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(_upgrade_to_head)
            await connection.commit()
    finally:
        await engine.dispose()


def _upgrade_to_head(connection: Connection) -> None:
    config = alembic_config()
    config.attributes["connection"] = connection
    command.upgrade(config, "head")
