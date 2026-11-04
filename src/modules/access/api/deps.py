"""Autorização HTTP; X-User-Id é aceito somente no ambiente local de dev/test."""

# FastAPI dependencies are declared as parameter defaults by design.

from collections.abc import Callable, Coroutine
from typing import Any, cast

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import AppEnv
from src.core.session import get_session
from src.modules.access.application.autorizacao import autorizar
from src.modules.access.application.ports import AccessReader
from src.modules.access.domain.usuario import UsuarioAutenticado

_SESSION_DEP = Depends(get_session)


def require(permissao: str) -> Callable[..., Coroutine[Any, Any, UsuarioAutenticado]]:
    async def dependency(
        request: Request,
        x_user_id: int | None = Header(default=None, alias="X-User-Id"),
        session: AsyncSession = _SESSION_DEP,
    ) -> UsuarioAutenticado:
        settings = request.app.state.settings
        if settings.app_env is AppEnv.PROD or x_user_id is None or x_user_id <= 0:
            raise HTTPException(status_code=401, detail="É preciso se autenticar.")
        repository_factory = cast(
            Callable[[AsyncSession], AccessReader], request.app.state.access_repository_factory
        )
        usuario = await repository_factory(session).get_usuario(x_user_id)
        if usuario is None:
            raise HTTPException(status_code=401, detail="É preciso se autenticar.")
        autorizar(usuario, permissao)
        return usuario

    dependency.__name__ = f"require_{permissao.replace(':', '_')}"
    return dependency
