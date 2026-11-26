"""Portas do módulo de acesso.

Os repositórios trabalham sobre a transação de quem os usa: quem chama abre, confirma ou desfaz.
"""

from collections.abc import Collection, Sequence
from datetime import datetime
from typing import Protocol
from uuid import UUID

from src.modules.access.domain.atribuicoes import Atribuicao, DadosDoUsuario, Papel
from src.modules.access.domain.authorization import Alvo, Concessao
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


class RepositorioDeAtribuicoes(Protocol):
    """Papéis, atribuições e dados básicos do usuário (spec 003, R2 e R5)."""

    async def papeis(self) -> Sequence[Papel]: ...

    async def papel(self, codigo: str) -> Papel | None: ...

    async def usuario(self, usuario_id: UUID) -> DadosDoUsuario | None: ...

    async def atribuicoes(self, usuario_id: UUID | None, agora: datetime) -> Sequence[Atribuicao]:
        """As vigentes do usuário; com `None`, de todos."""
        ...

    async def atribuicao(self, id_: UUID) -> Atribuicao | None: ...

    async def escopo_existe(self, nivel: str, id_do_escopo: str) -> bool: ...

    async def inserir(self, atribuicao: Atribuicao) -> None: ...

    async def remover(self, id_: UUID) -> None: ...


class RepositorioDeMapeamentos(Protocol):
    """Mapeamentos grupo→papel (R3) e as atribuições derivadas deles."""

    async def grupo_existe(self, grupo_id: UUID) -> bool:
        """Se o grupo está em `groups` (spec 004), ativo ou não (FK do mapeamento)."""
        ...

    async def ha_mapeamento(
        self, grupo_id: UUID, papel: str, escopo_tipo: str, escopo_id: str | None
    ) -> bool:
        """Se o grupo já está mapeado para o papel no escopo."""
        ...

    async def inserir(self, mapeamento: MapeamentoDeGrupo) -> None: ...

    async def obter(self, mapeamento_id: UUID) -> MapeamentoDeGrupo | None: ...

    async def remover(self, mapeamento_id: UUID) -> None:
        """Apaga o mapeamento; as derivadas dele já devem ter saído."""
        ...

    async def listar(self) -> Sequence[MapeamentoDeGrupo]:
        """Todos os mapeamentos, na ordem de criação."""
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
