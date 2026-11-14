"""Histórico de uma unidade: filtros, página pedida e eventos lidos da trilha (spec 008, R1;
spec 011, R4.5).

Valores que entram e saem da porta `HistoricoDeUnidades`, sem banco nem HTTP. Os eventos são
os que o `audit.registrar` gravou no nível da unidade, inclusive os dos seus equipamentos e
serviços (006/R5.3).
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class FiltrosDoHistorico:
    """Filtros opcionais do histórico (008/R1.3), que se somam: período com as duas pontas
    incluídas (`de`, `ate`, com fuso), autor (id do usuário) e campo (o nome gravado na lista
    {campo, de, para} do evento)."""

    de: datetime | None = None
    ate: datetime | None = None
    autor: UUID | None = None
    campo: str | None = None


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
class MudancaNoHistorico:
    """Um campo alterado num evento, com os valores JSON como a trilha os guardou."""

    campo: str
    de: Any
    para: Any


@dataclass(frozen=True, slots=True)
class EventoDoHistorico:
    """Um evento da unidade: quando, quem (nome e papéis no momento), o quê e os campos
    alterados. Sem autor (tarefa do sistema), os campos do autor vêm nulos ou vazios."""

    id: int
    ocorrido_em: datetime
    acao: str
    autor_id: UUID | None
    autor_nome: str | None
    autor_papeis: tuple[str, ...]
    mudancas: tuple[MudancaNoHistorico, ...]
    metadados: Mapping[str, Any] = field(default_factory=dict)
