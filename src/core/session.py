"""Sessão transacional por requisição HTTP."""

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors import Conflict, DomainValidationError, FieldError


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with AsyncSession(request.app.state.engine) as session:
        try:
            async with session.begin():
                yield session
        except IntegrityError as error:
            sqlstate = getattr(error.orig, "sqlstate", None)
            if sqlstate == "23505":
                raise Conflict("O registro já existe.") from None
            if sqlstate in {"23503", "23514", "23502", "22001"}:
                raise DomainValidationError(
                    "Os dados não atendem às regras do cadastro.",
                    errors=[FieldError(campo="dados", mensagem="Confira os campos informados.")],
                ) from None
            raise
