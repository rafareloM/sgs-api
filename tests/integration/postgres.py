"""Apoio aos testes que usam PostgreSQL de verdade (fixtures em tests/integration/conftest.py)."""

from dataclasses import dataclass

from sqlalchemy import URL
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

# Login usado pela API nos testes: membro do papel sgs_app, como o sgs_api do compose.
LOGIN_DA_API = "sgs_api_teste"
SENHA_DA_API = "sgs_api_teste"  # banco descartável de teste


@dataclass(frozen=True)
class BancoDeTeste:
    """Banco exclusivo de um teste: URL do dono (migra, superusuário) e do login da API."""

    url_dono: str
    url_api: str


def como_texto(url: URL) -> str:
    return url.render_as_string(hide_password=False)


def motor(url: str) -> AsyncEngine:
    """Engine sem pool: cada teste abre e fecha as próprias conexões."""
    return create_async_engine(url, poolclass=NullPool)
