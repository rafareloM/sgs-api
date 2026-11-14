"""Autenticação de uma requisição pelo access token (spec 002, R3.8; design § Componentes).

O token prova a assinatura, o emissor, o público e a validade; a revogação não está nele. Por
isso a sessão `sid` e o usuário `sub` são lidos a cada requisição: sessão revogada (logout,
reuso de refresh) ou usuário desativado deixam de passar na hora, sem esperar o token vencer.
"""

from dataclasses import dataclass
from uuid import UUID

from src.modules.identity.domain.ports import SessionRepository, UserRepository
from src.modules.identity.domain.tokens import InvalidTokenError, TokenService

# Reexportados para a camada api, que só importa a application (design da 002, Decisões).
__all__ = [
    "InvalidTokenError",
    "SessionRepository",
    "TokenService",
    "UserRepository",
    "UsuarioAutenticado",
    "autenticar",
]


@dataclass(frozen=True)
class UsuarioAutenticado:
    """Quem fez a requisição: o usuário e a sessão do access token."""

    id: UUID
    sessao_id: UUID


async def autenticar(
    token: str, *, tokens: TokenService, usuarios: UserRepository, sessoes: SessionRepository
) -> UsuarioAutenticado:
    """Levanta `InvalidTokenError` (401), sempre com a mesma mensagem, se o token não vale, se
    a sessão não existe, foi revogada ou é de outro usuário, ou se o usuário está desativado."""
    claims = tokens.verify_access_token(token)
    sessao = await sessoes.get_by_id(claims.session_id)
    if sessao is None or sessao.revoked_at is not None or sessao.user_id != claims.user_id:
        raise InvalidTokenError
    usuario = await usuarios.get_by_id(claims.user_id)
    if usuario is None or not usuario.is_active:
        raise InvalidTokenError
    return UsuarioAutenticado(id=usuario.id, sessao_id=sessao.id)
