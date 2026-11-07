"""`CurrentUser`: o usuário do access token da requisição (spec 002, design § Componentes; R3.8).

Rotas não usam esta dependência direto: declaram a permissão com `require()` (access.api.deps),
que autentica por aqui antes de autorizar.
"""

from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.modules.identity.application.autenticacao import (
    InvalidTokenError,
    SessionRepository,
    TokenService,
    UserRepository,
    UsuarioAutenticado,
    autenticar,
)

_bearer = HTTPBearer(auto_error=False, description="Access token JWT emitido no login (spec 002).")

# RFC 6750 e RFC 9110: o 401 diz ao cliente qual esquema usar.
_DESAFIO = {"WWW-Authenticate": "Bearer"}


async def usuario_atual(
    request: Request,
    credenciais: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> UsuarioAutenticado:
    if credenciais is None:
        raise HTTPException(401, headers=_DESAFIO)
    estado = request.app.state
    tokens: TokenService = estado.token_service
    try:
        async with estado.sessoes() as sessao:
            usuarios: UserRepository = estado.repositorio_de_usuarios(sessao)
            sessoes: SessionRepository = estado.repositorio_de_sessoes(sessao)
            return await autenticar(
                credenciais.credentials, tokens=tokens, usuarios=usuarios, sessoes=sessoes
            )
    except InvalidTokenError as erro:
        raise HTTPException(401, detail=erro.detail, headers=_DESAFIO) from None


CurrentUser = Annotated[UsuarioAutenticado, Depends(usuario_atual)]
