"""Schemas de saída das consultas do dashboard (design da 011 § Rotas).

Lidos dos valores do domínio (`model_validate` com `from_attributes`), nunca de linhas do banco.
"""

from uuid import UUID

from pydantic import BaseModel, ConfigDict

from src.modules.dashboard.application.consultas import SituacaoConciliacao


class UnidadeResumoOut(BaseModel):
    """Unidade numa consulta de qualidade; `tipo` e `distrito` são os nomes, para leitura."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    nome: str
    cnes: str | None
    tipo: str
    distrito: str


class ConciliacaoOut(BaseModel):
    """Linha da conciliação unidade x equipamento; o lado que faltar vem nulo. `distrito` é o
    nome do distrito da unidade e `equipamento_tipo`, o nome do tipo do equipamento."""

    model_config = ConfigDict(from_attributes=True)

    unidade_id: UUID | None
    unidade_nome: str | None
    distrito: str | None
    equipamento_id: UUID | None
    equipamento_nome: str | None
    equipamento_tipo: str | None
    situacao: SituacaoConciliacao
