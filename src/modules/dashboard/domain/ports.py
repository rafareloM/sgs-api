"""Portas do módulo de dashboard.

As consultas trabalham sobre a sessão de quem as usa, só para leitura.
"""

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from src.modules.dashboard.domain.consultas import (
    Filtros,
    ItemConciliacao,
    Pagina,
    Resultado,
    UnidadeResumo,
)


class EscopoDeLeitura(Protocol):
    """O que uma consulta lê do escopo de leitura do usuário (`EscopoLeitura` da spec 003):
    tudo, se `global_`; senão, as áreas técnicas, os distritos e as unidades listados."""

    @property
    def global_(self) -> bool: ...

    @property
    def areas(self) -> Sequence[int]: ...

    @property
    def distritos(self) -> Sequence[int]: ...

    @property
    def unidades(self) -> Sequence[UUID]: ...


class ConsultasDashboard(Protocol):
    """Consultas de qualidade do cadastro, cada uma limitada ao escopo e aos filtros dados
    (design da 011 § Consultas; ADR-0009)."""

    async def distrito_existe(self, distrito: int) -> bool:
        """Se há distrito com esse id nas referências da 006, ativo ou não."""
        ...

    async def tipo_de_unidade_existe(self, tipo: int) -> bool:
        """Se há tipo de unidade com esse id nas referências da 006, ativo ou não."""
        ...

    async def unidades_sem_servico(
        self, escopo: EscopoDeLeitura, filtros: Filtros, pagina: Pagina
    ) -> Resultado[UnidadeResumo]:
        """Unidades não inativas sem nenhum serviço (011/R2.1), por distrito e nome."""
        ...

    async def conciliacao_unidade_equipamento(
        self, escopo: EscopoDeLeitura, filtros: Filtros, pagina: Pagina
    ) -> Resultado[ItemConciliacao]:
        """Pares unidade-equipamento, unidades sem equipamento e equipamentos sem unidade
        (011/R2.2). Os equipamentos sem unidade só vêm com escopo global e sem filtro (R2.6)."""
        ...
