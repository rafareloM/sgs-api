"""Raiz de composição da API: cria o app e liga as camadas dos módulos."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import version

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.core import health
from src.core.config import AppEnv, Settings, load_settings
from src.core.db import create_engine, run_migrations
from src.core.logging import configure_logging
from src.core.problem import install_error_handlers
from src.core.request_context import RequestContextMiddleware
from src.core.security_headers import SecurityHeadersMiddleware
from src.modules.access.application.permissoes import ResolvedorDePermissoes
from src.modules.access.infrastructure.repository import (
    SqlRepositorioDePermissoes,
    SqlResolvedorDeUnidade,
)
from src.modules.audit.infrastructure.repository import SqlAuditStore
from src.modules.dashboard.api import rotas as dashboard
from src.modules.dashboard.infrastructure.consultas import SqlConsultasDashboard
from src.modules.identity.api import jwks
from src.modules.identity.infrastructure.repository import SqlSessionRepository, SqlUserRepository
from src.modules.identity.infrastructure.tokens import JwtTokenService
from src.modules.registry.api import unidades
from src.modules.registry.infrastructure.repository import SqlRepositorioDeUnidades


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
    app.state.sessoes = async_sessionmaker(app.state.engine, expire_on_commit=False)
    app.state.token_service = JwtTokenService.from_settings(settings)
    # Fábricas de repositórios: recebem a sessão SQLAlchemy de quem as usa (a camada api não
    # importa a infrastructure; design da 002, Decisões).
    app.state.repositorio_de_usuarios = SqlUserRepository
    app.state.repositorio_de_sessoes = SqlSessionRepository
    app.state.repositorio_de_permissoes = SqlRepositorioDePermissoes
    app.state.auditoria = SqlAuditStore
    app.state.repositorio_de_unidades = SqlRepositorioDeUnidades
    app.state.consultas_dashboard = SqlConsultasDashboard
    # Um resolvedor por processo: o cache de permissões é dele (design da 003, passo 3).
    app.state.resolvedor_de_permissoes = ResolvedorDePermissoes()
    # `ResourceRef.tipo` → fábrica do `ResolvedorDeAlvo` daquele tipo de recurso (design da 003,
    # § Verificação).
    app.state.resolvedores_de_alvo = {"unidade": SqlResolvedorDeUnidade}
    install_error_handlers(app)
    app.include_router(health.router)
    app.include_router(jwks.router)
    app.include_router(unidades.router)
    app.include_router(dashboard.router)

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
