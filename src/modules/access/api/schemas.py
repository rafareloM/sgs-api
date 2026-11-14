"""Schemas compartilhados pelas rotas do módulo de acesso."""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field

from src.modules.access.domain.authorization import Area, Distrito, Escopo, Global, Unidade

NivelDeEscopo = Literal["global", "area", "distrito", "unidade"]


class EscopoIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    tipo: NivelDeEscopo
    id: str | None = Field(
        default=None,
        min_length=1,
        max_length=36,
        description="Id da área técnica, do distrito ou da unidade; nulo se global.",
    )


class EscopoOut(BaseModel):
    tipo: NivelDeEscopo
    id: str | None = Field(
        description="Id da área técnica, do distrito ou da unidade, em texto; nulo se global."
    )

    @classmethod
    def de(cls, escopo: Escopo) -> Self:
        match escopo:
            case Global():
                return cls(tipo="global", id=None)
            case Area(id=id_):
                return cls(tipo="area", id=str(id_))
            case Distrito(id=id_):
                return cls(tipo="distrito", id=str(id_))
            case Unidade(id=id_):
                return cls(tipo="unidade", id=str(id_))
