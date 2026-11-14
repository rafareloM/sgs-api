"""Busca e detalhe da unidade de saúde (spec 006, R2; design § Busca)."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from src.modules.registry.domain.unidade import Unidade

Ordenacao = Literal["relevancia", "nome", "distrito", "atualizacao"]
"""Ordem da listagem (R2.4): por nome, pelo nome do distrito (e nome dentro dele) ou pela data de
atualização, a mais recente primeiro. `relevancia` (semelhança com o texto livre, design § Busca)
é a ordem quando há texto livre e nenhuma foi pedida."""


@dataclass(frozen=True, slots=True)
class FiltrosDeUnidades:
    """Filtros combináveis da listagem (R2.2, R2.3); `None` é sem filtro."""

    texto: str | None = None
    tipo: int | None = None
    area: int | None = None
    distrito: int | None = None
    status: str | None = None
    com_pendencias: bool | None = None


def ordem_efetiva(pedida: Ordenacao | None, filtros: FiltrosDeUnidades) -> Ordenacao:
    """A ordem pedida; sem pedido, semelhança se há texto livre, senão nome (R2.4)."""
    if pedida is not None:
        return pedida
    return "relevancia" if filtros.texto is not None else "nome"


@dataclass(frozen=True, slots=True)
class PaginaPedida:
    """Página pedida: número (a partir de 1) e itens por página (R2.1)."""

    numero: int
    tamanho: int

    @property
    def offset(self) -> int:
        return (self.numero - 1) * self.tamanho


@dataclass(frozen=True, slots=True)
class PaginaDeUnidades:
    """As unidades de uma página e o total da listagem inteira (R2.1)."""

    itens: tuple[Unidade, ...]
    total: int


@dataclass(frozen=True, slots=True)
class EquipamentoDaUnidade:
    """Equipamento vinculado à unidade, como o detalhe o mostra (R2.5)."""

    id: UUID
    name: str
    cnes: str | None
    equipment_type_code: str
    quantity: int
    status: str


@dataclass(frozen=True, slots=True)
class ServicoDaUnidade:
    """Serviço vinculado à unidade, como o detalhe o mostra (R2.5)."""

    id: UUID
    name: str
    service_type_id: int
    equipment_id: UUID | None
    in_cnes: bool
    status: str


@dataclass(frozen=True, slots=True)
class DetalheDaUnidade:
    """A unidade com os equipamentos e serviços vinculados a ela (R2.5)."""

    unidade: Unidade
    equipamentos: Sequence[EquipamentoDaUnidade]
    servicos: Sequence[ServicoDaUnidade]
