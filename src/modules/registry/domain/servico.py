"""Serviço de saúde (spec 006, R6): de uma unidade, num equipamento dela, ou solto.

O serviço aponta a unidade e o equipamento pelo id, nunca pelo nome (R6.4).
"""

from dataclasses import asdict, dataclass, fields
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class DadosDoServico:
    """Os campos de negócio do serviço, com os nomes das colunas de `services`."""

    service_type_id: int
    equipment_id: UUID | None
    name: str
    in_cnes: bool
    status: str


CAMPOS_DO_SERVICO = tuple(campo.name for campo in fields(DadosDoServico))
"""Colunas de negócio do serviço, na ordem da tabela."""


@dataclass(frozen=True, slots=True)
class Servico(DadosDoServico):
    """O serviço como está no banco; `unit_id` nulo é o serviço solto (R6.2)."""

    id: UUID
    unit_id: UUID | None
    created_at: datetime
    updated_at: datetime

    def campos_de_negocio(self) -> dict[str, object]:
        """Coluna → valor, só dos campos de negócio, na ordem de `CAMPOS_DO_SERVICO`."""
        todos = asdict(self)
        return {campo: todos[campo] for campo in CAMPOS_DO_SERVICO}
