"""Endpoints JSON agregados do dashboard."""

from collections.abc import Callable
from typing import Any, cast

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors import DomainValidationError, FieldError
from src.core.session import get_session
from src.modules.access.api.deps import require
from src.modules.access.domain.usuario import UsuarioAutenticado
from src.modules.dashboard.application.ports import DashboardReader

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])
_DASHBOARD_READ = require("dashboard:read")
_DASHBOARD_READ_DEP = Depends(_DASHBOARD_READ)
_SESSION_DEP = Depends(get_session)


@router.get("/resumo")
async def get_resumo(
    request: Request,
    distrito: str | None = Query(default=None, max_length=50),
    area: str | None = Query(default=None, max_length=50),
    usuario: UsuarioAutenticado = _DASHBOARD_READ_DEP,
    session: AsyncSession = _SESSION_DEP,
) -> dict[str, Any]:
    if area is not None:
        raise DomainValidationError(
            "Filtro por área técnica indisponível no schema legado.",
            errors=[FieldError(campo="area", mensagem="A Etapa 02 não armazena área técnica.")],
        )
    factory = cast(
        Callable[[AsyncSession], DashboardReader], request.app.state.dashboard_repository_factory
    )
    return await factory(session).resumo(distrito=distrito, id_unidade=usuario.id_unidade)
