"""Permissões efetivas de um usuário (spec 003, design § Resolução de permissões)."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from uuid import UUID

from src.modules.access.domain.authorization import PermissoesEfetivas, permissoes_efetivas
from src.modules.access.domain.ports import RepositorioDePermissoes

TTL = timedelta(seconds=30)

SEM_PERMISSOES: PermissoesEfetivas = MappingProxyType({})


def _agora() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class _Entrada:
    versao: int
    permissoes: PermissoesEfetivas
    expira_em: datetime


class ResolvedorDePermissoes:
    """Resolve as permissões efetivas com cache em memória por usuário (passo 3 do design).

    Uma instância por processo. A cada chamada, lê `users.authz_version`: se mudou desde que a
    entrada foi guardada, recarrega (R4.5). Com a mesma versão, a entrada vale por 30 s, o que
    limita o atraso de uma alteração feita sem incrementar a versão, ou até a primeira
    atribuição dela expirar, o que vier antes.
    """

    def __init__(self, *, relogio: Callable[[], datetime] = _agora) -> None:
        self._relogio = relogio
        self._cache: dict[UUID, _Entrada] = {}

    async def permissoes_de(
        self, repositorio: RepositorioDePermissoes, usuario_id: UUID
    ) -> PermissoesEfetivas:
        # A versão vem antes das concessões: se uma alteração for confirmada entre as duas
        # leituras, a entrada fica com a versão antiga e a próxima chamada recarrega.
        versao = await repositorio.versao(usuario_id)
        if versao is None:
            self._cache.pop(usuario_id, None)
            return SEM_PERMISSOES
        agora = self._relogio()
        entrada = self._cache.get(usuario_id)
        if entrada is not None and entrada.versao == versao and agora < entrada.expira_em:
            return entrada.permissoes
        concessoes = await repositorio.concessoes(usuario_id, agora)
        permissoes = permissoes_efetivas(concessoes)
        # A entrada não passa da primeira expiração de atribuição (R2.3).
        expira_em = min(
            [agora + TTL, *(c.valido_ate for c in concessoes if c.valido_ate is not None)]
        )
        self._cache[usuario_id] = _Entrada(versao, permissoes, expira_em)
        return permissoes
