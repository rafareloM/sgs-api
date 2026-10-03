"""Raiz de composição da API: cria o app e liga as camadas dos módulos."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import version

from fastapi import FastAPI

from src.core import health
from src.core.config import AppEnv, Settings, load_settings
from src.core.db import create_engine, run_migrations
from src.core.logging import configure_logging
from src.core.problem import install_error_handlers
from src.core.request_context import RequestContextMiddleware


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    if settings.app_env is AppEnv.DEV and settings.database_migration_url is not None:
        # Em dev a subida aplica as migrações (R1.2); em test e prod elas são um passo à parte.
        await run_migrations(settings.database_migration_url.get_secret_value(), settings)
    try:
        yield
    finally:
        await app.state.engine.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Fábrica do app. Sem argumento, lê a configuração do ambiente (`uvicorn --factory`)."""
    settings = settings or load_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title="SGS · API de Governança de Dados de Saúde",
        version=version("sgs-api"),
        lifespan=_lifespan,
    )
    app.state.settings = settings
    # A engine só abre conexões quando usada; criar o app não exige banco no ar.
    app.state.engine = create_engine(settings.database_url.get_secret_value(), settings)
    install_error_handlers(app)
    app.include_router(health.router)
    # Adicionado por último para envolver todos os outros middlewares.
    app.add_middleware(RequestContextMiddleware)
    return app
