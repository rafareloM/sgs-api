"""Raiz de composição da API: cria o app e liga as camadas dos módulos."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import version

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.core import health
from src.core.config import AppEnv, Settings, load_settings
from src.core.db import create_engine, run_migrations
from src.core.logging import configure_logging
from src.core.problem import install_error_handlers
from src.core.request_context import RequestContextMiddleware
from src.core.security_headers import SecurityHeadersMiddleware


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

    # Documentação OpenAPI só em dev e test (R6.3).
    public_docs = settings.app_env is not AppEnv.PROD
    app = FastAPI(
        title="SGS · API de Governança de Dados de Saúde",
        version=version("sgs-api"),
        lifespan=_lifespan,
        openapi_url="/openapi.json" if public_docs else None,
        docs_url="/docs" if public_docs else None,
        redoc_url="/redoc" if public_docs else None,
    )
    app.state.settings = settings
    # A engine só abre conexões quando usada; criar o app não exige banco no ar.
    app.state.engine = create_engine(settings.database_url.get_secret_value(), settings)
    install_error_handlers(app)
    app.include_router(health.router)

    # O último middleware adicionado é o mais externo: contexto > cabeçalhos > CORS > rotas.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),  # só as origens configuradas (R6.2)
        allow_credentials=True,  # o refresh token da 002 viaja em cookie
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Requested-With", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
        max_age=600,
    )
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestContextMiddleware)
    return app
