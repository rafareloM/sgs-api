"""Portas do módulo de acesso.

Os repositórios trabalham sobre a transação de quem os usa: quem chama abre, confirma ou desfaz.
"""

from collections.abc import Collection, Sequence
from datetime import datetime
from typing import Protocol
from uuid import UUID

from src.modules.access.domain.atribuicoes import Atribuicao
from src.modules.access.domain.authorization import Alvo, Concessao, Escopo, PapelAtribuido
from src.modules.access.domain.mapeamentos import MapeamentoDeGrupo


class RepositorioDePermissoes(Protocol):
    async def versao(self, usuario_id: UUID) -> int | None:
        """`users.authz_version` do usuário; `None` se ele não existe."""
        ...

    async def concessoes(self, usuario_id: UUID, agora: datetime) -> Sequence[Concessao]:
        """Uma concessão por permissão de cada atribuição do usuário (direta ou de grupo) que
        não tenha expirado até `agora`."""
        ...

    async def invalidar(self, usuario_id: UUID) -> None:
        """Incrementa `users.authz_version`. Quem altera as atribuições de um usuário chama na
        mesma transação, e a mudança vale na próxima requisição (003/R4.5)."""
        ...


class RepositorioDePapeis(Protocol):
    async def papeis(self, usuario_id: UUID, agora: datetime) -> Sequence[PapelAtribuido]:
        """As atribuições do usuário (diretas ou de grupo) que não tenham expirado até `agora`,
        na ordem do código do papel."""
        ...


class RepositorioDeAtribuicoes(Protocol):
    """Atribuições de papel para a administração (R2)."""

    async def escopos_maximos(self, papel: str) -> frozenset[str] | None:
        """Os `max_scope` das permissões do papel de código `papel`; `None` se ele não existe."""
        ...

    async def escopo_existe(self, escopo: Escopo) -> bool:
        """Se a área técnica, o distrito ou a unidade existe (global sempre existe)."""
        ...

    async def ha_direta_vigente(
        self, usuario_id: UUID, papel: str, escopo: Escopo, agora: datetime
    ) -> bool:
        """Se o usuário já tem, direta e não expirada até `agora`, a mesma atribuição."""
        ...

    async def inserir(self, atribuicao: Atribuicao) -> None: ...

    async def obter(self, atribuicao_id: UUID) -> Atribuicao | None: ...

    async def remover(self, atribuicao_id: UUID) -> None: ...

    async def listar(
        self, usuario_id: UUID | None, agora: datetime, *, deslocamento: int, limite: int
    ) -> tuple[Sequence[Atribuicao], int]:
        """Uma página das atribuições não expiradas até `agora`, de um usuário ou de todos, na
        ordem de criação, e o total da listagem."""
        ...


class RepositorioDeMapeamentos(Protocol):
    """Mapeamentos grupo→papel (R3) e as atribuições derivadas deles."""

    async def ha_mapeamento(self, grupo_id: UUID, papel: str, escopo: Escopo) -> bool:
        """Se o grupo já está mapeado para o papel no escopo."""
        ...

    async def inserir(self, mapeamento: MapeamentoDeGrupo) -> None: ...

    async def obter(self, mapeamento_id: UUID) -> MapeamentoDeGrupo | None: ...

    async def remover(self, mapeamento_id: UUID) -> None:
        """Apaga o mapeamento; as derivadas dele já devem ter saído."""
        ...

    async def listar(
        self, *, deslocamento: int, limite: int
    ) -> tuple[Sequence[MapeamentoDeGrupo], int]:
        """Uma página dos mapeamentos, na ordem de criação, e o total."""
        ...

    async def dos_grupos(self, grupos: Collection[UUID]) -> Sequence[MapeamentoDeGrupo]:
        """Os mapeamentos dos grupos dados."""
        ...

    async def derivadas_do_usuario(self, usuario_id: UUID) -> Sequence[Atribuicao]:
        """As atribuições de origem `group` do usuário, expiradas ou não."""
        ...

    async def derivadas_do_mapeamento(self, mapeamento_id: UUID) -> Sequence[Atribuicao]:
        """As atribuições geradas pelo mapeamento."""
        ...


class MembrosDeGrupo(Protocol):
    """Quem está num grupo do diretório (spec 004: `groups` e `user_groups`)."""

    async def membros_ativos(self, grupo_id: UUID) -> frozenset[UUID]:
        """Os ids dos usuários ativos membros do grupo; vazio se o grupo não existe."""
        ...


class ResolvedorDeAlvo(Protocol):
    """Acha os atributos de escopo de um tipo de recurso (design § Verificação, `ResourceRef`).

    Uma implementação por tipo, registrada pela raiz de composição em
    `app.state.resolvedores_de_alvo`; a unidade, por exemplo, dá o próprio id, o distrito e a
    área técnica do seu tipo.
    """

    async def alvo(self, id_do_recurso: str) -> Alvo | None:
        """`None` se o recurso não existe. O id chega em texto, como veio no caminho; um id fora
        do formato do recurso também é `None`."""
        ...
