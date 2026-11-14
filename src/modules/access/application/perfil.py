"""Perfil do usuário logado (spec 003, R5.1; design § Rotas, `GET /api/v1/me`)."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from src.core.errors import NotFound
from src.modules.access.application.permissoes import ResolvedorDePermissoes
from src.modules.access.domain.authorization import PapelAtribuido, PermissoesEfetivas
from src.modules.access.domain.ports import RepositorioDePapeis, RepositorioDePermissoes
from src.modules.identity.application.autenticacao import UserRepository

__all__ = ["Perfil", "perfil_do_usuario"]


@dataclass(frozen=True)
class Perfil:
    """Dados básicos do usuário, papéis vigentes com escopo e permissões efetivas. Só o que o
    front precisa para montar a tela inicial: nada de hash, token ou id externo."""

    id: UUID
    username: str
    nome: str
    email: str | None
    papeis: Sequence[PapelAtribuido]
    permissoes: PermissoesEfetivas


async def perfil_do_usuario(
    usuario_id: UUID,
    *,
    usuarios: UserRepository,
    papeis: RepositorioDePapeis,
    permissoes: RepositorioDePermissoes,
    resolvedor: ResolvedorDePermissoes,
    agora: datetime | None = None,
) -> Perfil:
    """As permissões vêm do mesmo resolvedor que o `require()` usa, para o perfil bater com o
    que a API autoriza."""
    usuario = await usuarios.get_by_id(usuario_id)
    if usuario is None:
        # O `CurrentUser` acabou de confirmar o usuário; só some se for apagado no meio.
        raise NotFound("Usuário não encontrado.")
    return Perfil(
        id=usuario.id,
        username=usuario.username,
        nome=usuario.display_name,
        email=usuario.email,
        papeis=await papeis.papeis(usuario_id, agora or datetime.now(UTC)),
        permissoes=await resolvedor.permissoes_de(permissoes, usuario_id),
    )
