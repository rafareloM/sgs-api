"""Schemas de entrada do CRUD raw da Etapa 03."""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

StatusUnidade = Literal["Ativa", "Inativa", "Em reforma", "Suspensa"]
TipoUnidade = Literal[
    "UBS",
    "UPA",
    "Hospital",
    "Laboratório",
    "Posto de Saúde",
    "Centro de Saúde",
]
TipoEquipamento = Literal[
    "Monitor de sinais vitais",
    "Respirador",
    "Tomógrafo",
    "Ultrassom",
    "Balança",
    "Aparelho de RX",
    "Cadeira de rodas",
    "Desfibrilador",
    "Fitas de esterilização",
    "Estetoscópio",
]


class UnidadeCreateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    codigocnes: str | None = Field(default=None, pattern=r"^[0-9]{7}$")
    nome: str = Field(min_length=1, max_length=150)
    tipo: TipoUnidade
    endereco: str = Field(min_length=1, max_length=200)
    cep: str = Field(pattern=r"^[0-9]{8}$")
    distritosanitario: str = Field(min_length=1, max_length=50)
    telefone: str | None = Field(default=None, max_length=15)
    status: StatusUnidade = "Ativa"


class UnidadeStatusPatchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: StatusUnidade
    motivo: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def motivo_obrigatorio_para_inativar(self) -> Self:
        if self.status == "Inativa" and not (self.motivo and self.motivo.strip()):
            raise ValueError("Informe o motivo da desativação.")
        return self


class EquipamentoCreateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nome: str = Field(min_length=1, max_length=100)
    tipo: TipoEquipamento
    quantidade: int = Field(ge=0, le=5000)


class EquipamentoPatchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nome: str | None = Field(default=None, min_length=1, max_length=100)
    tipo: TipoEquipamento | None = None
    quantidade: int | None = Field(default=None, ge=0, le=5000)

    @model_validator(mode="after")
    def patch_nao_vazio(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("Informe ao menos um campo para atualizar.")
        return self
