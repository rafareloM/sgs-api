"""Equipamento de saúde (spec 006, R5): de uma unidade ou sem unidade, como a UTI móvel."""

from dataclasses import asdict, dataclass, fields
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class DadosDoEquipamento:
    """Os campos de negócio do equipamento, com os nomes das colunas de `equipments`."""

    name: str
    cnes: str | None
    equipment_type_code: str
    quantity: int
    status: str


CAMPOS_DO_EQUIPAMENTO = tuple(campo.name for campo in fields(DadosDoEquipamento))
"""Colunas de negócio do equipamento, na ordem da tabela."""


@dataclass(frozen=True, slots=True)
class Equipamento(DadosDoEquipamento):
    """O equipamento como está no banco; `unit_id` nulo é o equipamento sem unidade (R5.2)."""

    id: UUID
    unit_id: UUID | None
    created_at: datetime
    updated_at: datetime

    def campos_de_negocio(self) -> dict[str, object]:
        """Coluna → valor, só dos campos de negócio, na ordem de `CAMPOS_DO_EQUIPAMENTO`."""
        todos = asdict(self)
        return {campo: todos[campo] for campo in CAMPOS_DO_EQUIPAMENTO}
