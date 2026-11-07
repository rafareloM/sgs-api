"""Consultas de qualidade do cadastro: filtros, página pedida e linhas de resultado (spec 011, R2).

O dashboard só lê: aqui ficam os valores que entram e saem da porta `ConsultasDashboard`, sem
banco nem HTTP.
"""

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


@dataclass(frozen=True, slots=True)
class Filtros:
    """Filtros opcionais de uma consulta (011/R2.7): ids de distrito e de tipo de unidade."""

    distrito: int | None = None
    tipo: int | None = None


@dataclass(frozen=True, slots=True)
class Pagina:
    """Página pedida: número (a partir de 1) e quantidade de itens por página."""

    numero: int
    tamanho: int

    @property
    def offset(self) -> int:
        return (self.numero - 1) * self.tamanho


@dataclass(frozen=True, slots=True)
class Resultado[T]:
    """Os itens de uma página e o total de itens da consulta inteira."""

    itens: tuple[T, ...]
    total: int


@dataclass(frozen=True, slots=True)
class UnidadeResumo:
    """Uma unidade numa consulta de qualidade: tipo e distrito pelo nome, para leitura."""

    id: UUID
    nome: str
    cnes: str | None
    tipo: str
    distrito: str


class SituacaoConciliacao(StrEnum):
    """Lado da conciliação unidade x equipamento em que a linha caiu (011/R2.2)."""

    PAR = "par"
    UNIDADE_SEM_EQUIPAMENTO = "unidade_sem_equipamento"
    EQUIPAMENTO_SEM_UNIDADE = "equipamento_sem_unidade"


@dataclass(frozen=True, slots=True)
class ItemConciliacao:
    """Uma linha da conciliação: a unidade, o equipamento ou os dois (`par`). O lado que faltar
    vem nulo; `distrito` é o nome do distrito da unidade e `equipamento_tipo`, o nome do tipo."""

    unidade_id: UUID | None
    unidade_nome: str | None
    distrito: str | None
    equipamento_id: UUID | None
    equipamento_nome: str | None
    equipamento_tipo: str | None
    situacao: SituacaoConciliacao
