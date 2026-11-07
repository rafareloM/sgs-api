"""Schemas de entrada e saída da unidade (design da 006 § Schemas).

O formato é conferido aqui (tamanhos, CNES com 7 dígitos, CEP com 8, status); as regras de
negócio ficam nos casos de uso. Os campos da API estão em português; os do domínio e do banco, em
inglês (`nome` ↔ `name`).
"""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal, Self, cast
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from src.modules.registry.application.unidades import DadosDaUnidade, Unidade

StatusDaUnidade = Literal["ativa", "inativa", "em_implantacao"]

# Ids das referências são `smallint` no banco.
_IdDeReferencia = Annotated[int, Field(ge=1, le=32767)]

# `[0-9]` e não `\d`, que no Pydantic também aceita dígitos de outros alfabetos.
_Cnes = Annotated[str, Field(pattern=r"^[0-9]{7}$", description="Sete dígitos.")]
_Cep = Annotated[
    str,
    Field(pattern=r"^[0-9]{5}-?[0-9]{3}$", description="Oito dígitos, com ou sem hífen."),
    # O banco guarda só os dígitos (`varchar(8)`).
    AfterValidator(lambda cep: cep.replace("-", "")),
]
_Telefone = Annotated[str, Field(min_length=1, max_length=20, pattern=r"^[0-9()+\- ]+$")]


class UnidadeCreate(BaseModel):
    """Unidade nova (006/R1.2: nome, tipo, distrito, endereço com CEP e status obrigatórios)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    nome: str = Field(min_length=1, max_length=200)
    cnes: _Cnes | None = Field(default=None, description="Sem CNES, a unidade fica pendente.")
    tipo_unidade_id: _IdDeReferencia
    distrito_id: _IdDeReferencia
    cep: _Cep
    endereco: str = Field(min_length=1, max_length=200)
    bairro: str | None = Field(default=None, min_length=1, max_length=100)
    telefone: _Telefone | None = None
    nome_gestor: str | None = Field(default=None, min_length=1, max_length=150)
    latitude: Decimal | None = Field(default=None, ge=-90, le=90, max_digits=9, decimal_places=6)
    longitude: Decimal | None = Field(default=None, ge=-180, le=180, max_digits=9, decimal_places=6)
    status: StatusDaUnidade

    def dados(self) -> DadosDaUnidade:
        return DadosDaUnidade(
            name=self.nome,
            cnes=self.cnes,
            unit_type_id=self.tipo_unidade_id,
            district_id=self.distrito_id,
            cep=self.cep,
            address=self.endereco,
            neighborhood=self.bairro,
            phone=self.telefone,
            manager_name=self.nome_gestor,
            latitude=self.latitude,
            longitude=self.longitude,
            status=self.status,
        )


class UnidadeOut(BaseModel):
    """A unidade completa. `versao` é a mesma do cabeçalho `ETag` (006/R3.2)."""

    id: UUID
    nome: str
    cnes: str | None
    cnes_pendente: bool
    tipo_unidade_id: int
    distrito_id: int
    cep: str
    endereco: str
    bairro: str | None
    telefone: str | None
    nome_gestor: str | None
    horario_funcionamento: dict[str, Any] | None
    latitude: float | None
    longitude: float | None
    status: StatusDaUnidade
    pendencias: int
    versao: int
    criado_em: datetime
    atualizado_em: datetime

    @classmethod
    def de(cls, unidade: Unidade) -> Self:
        return cls(
            id=unidade.id,
            nome=unidade.name,
            cnes=unidade.cnes,
            cnes_pendente=unidade.cnes_pendente,
            tipo_unidade_id=unidade.unit_type_id,
            distrito_id=unidade.district_id,
            cep=unidade.cep,
            endereco=unidade.address,
            bairro=unidade.neighborhood,
            telefone=unidade.phone,
            nome_gestor=unidade.manager_name,
            horario_funcionamento=(
                None if unidade.opening_hours is None else dict(unidade.opening_hours)
            ),
            latitude=None if unidade.latitude is None else float(unidade.latitude),
            longitude=None if unidade.longitude is None else float(unidade.longitude),
            status=cast(StatusDaUnidade, unidade.status),  # o CHECK do banco garante
            pendencias=unidade.pending_issues,
            versao=unidade.version,
            criado_em=unidade.created_at,
            atualizado_em=unidade.updated_at,
        )
