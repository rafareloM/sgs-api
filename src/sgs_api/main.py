"""Raiz de composição da API: cria o app e liga as camadas dos módulos."""

from importlib.metadata import version

from fastapi import FastAPI

from sgs_api.core import health
from sgs_api.core.config import Settings, load_settings
from sgs_api.core.logging import configure_logging
from sgs_api.core.problem import install_error_handlers
from sgs_api.core.request_context import RequestContextMiddleware


def create_app(settings: Settings | None = None) -> FastAPI:
    """Fábrica do app. Sem argumento, lê a configuração do ambiente (`uvicorn --factory`)."""
    settings = settings or load_settings()
    configure_logging(settings.log_level)

    app = FastAPI(title="SGS · API de Governança de Dados de Saúde", version=version("sgs-api"))
    app.state.settings = settings
    install_error_handlers(app)
    app.include_router(health.router)
    # Adicionado por último para envolver todos os outros middlewares.
    app.add_middleware(RequestContextMiddleware)
    return app
