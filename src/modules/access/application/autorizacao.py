"""Mapeamento de permissões do seed da Etapa 02 para as permissões HTTP."""

from src.core.errors import Forbidden
from src.modules.access.domain.usuario import UsuarioAutenticado

_ALIASES: dict[str, frozenset[str]] = {
    "unidade:create": frozenset({"cadastro_unidade", "gestao_dados"}),
    "unidade:read": frozenset(
        {"consulta_unidade", "cadastro_unidade", "edicao_unidade", "gestao_dados"}
    ),
    "unidade:update": frozenset({"edicao_unidade", "cadastro_unidade", "gestao_dados"}),
    "unidade:deactivate": frozenset({"gestao_dados"}),
    "equipamento:write": frozenset({"cadastro_equipamentos", "gestao_dados"}),
    "dashboard:read": frozenset({"dashboard", "gestao_dados"}),
}
_GLOBAL_ONLY = frozenset({"unidade:create", "unidade:deactivate"})


def autorizar(
    usuario: UsuarioAutenticado,
    permissao: str,
    *,
    unidade_id: int | None = None,
    colecao: bool = False,
    exigir_global: bool = False,
) -> None:
    permitidas = _ALIASES.get(permissao)
    if permitidas is None or not usuario.permissoes.intersection(permitidas):
        raise Forbidden("Você não tem permissão para esta ação.")
    if (permissao in _GLOBAL_ONLY or exigir_global) and "gestao_dados" not in usuario.permissoes:
        raise Forbidden("Esta ação exige permissão global.")
    if colecao and "gestao_dados" not in usuario.permissoes and usuario.id_unidade is None:
        raise Forbidden("Você não tem escopo de unidade para esta listagem.")
    if (
        unidade_id is not None
        and "gestao_dados" not in usuario.permissoes
        and usuario.id_unidade != unidade_id
    ):
        raise Forbidden("Você não tem acesso a esta unidade.")
