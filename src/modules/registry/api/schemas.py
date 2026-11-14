"""Schemas de entrada e saída da unidade (design da 006 § Schemas).

O formato é conferido aqui (tamanhos, CNES com 7 dígitos, CEP com 8, status); as regras de
negócio ficam nos casos de uso. Os campos da API estão em português; os do domínio e do banco, em
inglês (`nome` ↔ `name`).
"""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal, Self, cast
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator

from src.modules.registry.application.unidades import (
    DadosDaUnidade,
    DetalheDaUnidade,
    EquipamentoDaUnidade,
    ServicoDaUnidade,
    Unidade,
)

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


# Campo da API → coluna, para os campos que o PATCH aceita (os mesmos do cadastro).
_COLUNA = {
    "nome": "name",
    "cnes": "cnes",
    "tipo_unidade_id": "unit_type_id",
    "distrito_id": "district_id",
    "cep": "cep",
    "endereco": "address",
    "bairro": "neighborhood",
    "telefone": "phone",
    "nome_gestor": "manager_name",
    "latitude": "latitude",
    "longitude": "longitude",
    "status": "status",
}

# Obrigatórios no cadastro (006/R1.2): no PATCH podem faltar, mas não vir nulos.
_SEM_NULO = ("nome", "tipo_unidade_id", "distrito_id", "cep", "endereco", "status")


class UnidadeUpdate(BaseModel):
    """Alteração parcial da unidade (006/R3.1): só os campos enviados mudam. Mesmo formato do
    `UnidadeCreate`; um campo opcional enviado nulo é apagado (CNES nulo deixa a unidade
    pendente, R1.5), e um obrigatório não pode vir nulo. Corpo vazio não muda nada (R3.6)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    nome: str | None = Field(default=None, min_length=1, max_length=200)
    cnes: _Cnes | None = None
    tipo_unidade_id: _IdDeReferencia | None = None
    distrito_id: _IdDeReferencia | None = None
    cep: _Cep | None = None
    endereco: str | None = Field(default=None, min_length=1, max_length=200)
    bairro: str | None = Field(default=None, min_length=1, max_length=100)
    telefone: _Telefone | None = None
    nome_gestor: str | None = Field(default=None, min_length=1, max_length=150)
    latitude: Decimal | None = Field(default=None, ge=-90, le=90, max_digits=9, decimal_places=6)
    longitude: Decimal | None = Field(default=None, ge=-180, le=180, max_digits=9, decimal_places=6)
    status: StatusDaUnidade | None = None

    @field_validator(*_SEM_NULO)
    @classmethod
    def _sem_nulo(cls, valor: object) -> object:
        # Roda só para o campo enviado; o ausente fica com o padrão e não é validado.
        if valor is None:
            raise ValueError("Campo obrigatório: não pode ser nulo.")
        return valor

    def alteracoes(self) -> dict[str, object]:
        """Coluna → valor, só dos campos enviados."""
        return {_COLUNA[campo]: getattr(self, campo) for campo in self.model_fields_set}


class UnidadeDesativacao(BaseModel):
    """Pedido de desativação: o motivo vai para a auditoria (006/R4.1)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    motivo: str = Field(min_length=1, max_length=500)


class UnidadeNaListaOut(BaseModel):
    """O item da listagem de unidades (006/R2.1): a unidade sem os dados de contato do gestor
    (`nome_gestor` e `telefone`), que só saem no detalhe da unidade que a pessoa abriu
    (`steering/security.md` § LGPD, a escolha mais restritiva; 006, "Perguntas em aberto")."""

    id: UUID
    nome: str
    cnes: str | None
    cnes_pendente: bool
    tipo_unidade_id: int
    distrito_id: int
    cep: str
    endereco: str
    bairro: str | None
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
        return cls(**_campos_do_resumo(unidade))


class UnidadeOut(UnidadeNaListaOut):
    """A unidade completa. `versao` é a mesma do cabeçalho `ETag` (006/R3.2)."""

    telefone: str | None
    nome_gestor: str | None

    @classmethod
    def de(cls, unidade: Unidade) -> Self:
        return cls(
            **_campos_do_resumo(unidade),
            telefone=unidade.phone,
            nome_gestor=unidade.manager_name,
        )


def _campos_do_resumo(unidade: Unidade) -> dict[str, Any]:
    return {
        "id": unidade.id,
        "nome": unidade.name,
        "cnes": unidade.cnes,
        "cnes_pendente": unidade.cnes_pendente,
        "tipo_unidade_id": unidade.unit_type_id,
        "distrito_id": unidade.district_id,
        "cep": unidade.cep,
        "endereco": unidade.address,
        "bairro": unidade.neighborhood,
        "horario_funcionamento": (
            None if unidade.opening_hours is None else dict(unidade.opening_hours)
        ),
        "latitude": None if unidade.latitude is None else float(unidade.latitude),
        "longitude": None if unidade.longitude is None else float(unidade.longitude),
        "status": cast(StatusDaUnidade, unidade.status),  # o CHECK do banco garante
        "pendencias": unidade.pending_issues,
        "versao": unidade.version,
        "criado_em": unidade.created_at,
        "atualizado_em": unidade.updated_at,
    }


class EquipamentoOut(BaseModel):
    """Equipamento vinculado à unidade, no detalhe dela (006/R2.5)."""

    id: UUID
    nome: str
    cnes: str | None
    tipo_equipamento: str = Field(description="Código do tipo de equipamento.")
    quantidade: int
    status: str

    @classmethod
    def de(cls, equipamento: EquipamentoDaUnidade) -> Self:
        return cls(
            id=equipamento.id,
            nome=equipamento.name,
            cnes=equipamento.cnes,
            tipo_equipamento=equipamento.equipment_type_code,
            quantidade=equipamento.quantity,
            status=equipamento.status,
        )


class ServicoOut(BaseModel):
    """Serviço vinculado à unidade, no detalhe dela (006/R2.5). `no_cnes` diz se ele consta no
    CNES (006/R6.3)."""

    id: UUID
    nome: str
    tipo_servico_id: int
    equipamento_id: UUID | None
    no_cnes: bool
    status: str

    @classmethod
    def de(cls, servico: ServicoDaUnidade) -> Self:
        return cls(
            id=servico.id,
            nome=servico.name,
            tipo_servico_id=servico.service_type_id,
            equipamento_id=servico.equipment_id,
            no_cnes=servico.in_cnes,
            status=servico.status,
        )


class UnidadeDetalheOut(UnidadeOut):
    """A unidade completa com os equipamentos e serviços vinculados a ela (006/R2.5)."""

    equipamentos: list[EquipamentoOut]
    servicos: list[ServicoOut]

    @classmethod
    def do_detalhe(cls, detalhe: DetalheDaUnidade) -> Self:
        return cls(
            **UnidadeOut.de(detalhe.unidade).model_dump(),
            equipamentos=[EquipamentoOut.de(e) for e in detalhe.equipamentos],
            servicos=[ServicoOut.de(s) for s in detalhe.servicos],
        )
