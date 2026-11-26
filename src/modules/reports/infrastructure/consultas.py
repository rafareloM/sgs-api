"""Consultas dos relatórios em SQL escrito à mão (spec 005/T11; ADR-0009, complemento da 011).

Cada consulta está em `sql/<nome>.sql`, com o cabeçalho que a explica, e é lida uma vez, na carga
do módulo. O escopo gravado no pedido entra pelos parâmetros `:scope_*` do fragmento fixo
(`src.core.escopo.parametros_de_escopo`) e os filtros, pelos seus parâmetros: nenhum valor é
interpolado no texto.

A geração inteira roda numa conexão própria, em `REPEATABLE READ, READ ONLY`, e as linhas saem
por cursor do servidor (`stream`), em lotes: o arquivo pode ter até 1.000.000 de linhas, e
nenhuma delas fica toda na memória (design § Geração e envio, passo 2).
"""

import json
from collections.abc import AsyncGenerator, Mapping, Sequence
from pathlib import Path
from typing import Any

from sqlalchemy import Row
from sqlalchemy.ext.asyncio import AsyncEngine

from src.core.escopo import parametros_de_escopo
from src.core.sql import consulta
from src.modules.reports.domain.escopo import Escopo
from src.modules.reports.domain.filtros import Filtros, FiltrosDaTrilha, FiltrosDoInventario
from src.modules.reports.domain.ports import TAMANHO_DO_LOTE

_SQL = Path(__file__).parent / "sql"

_SOMENTE_LEITURA = consulta(_SQL / "transacao_somente_leitura.sql")
_INVENTARIO = consulta(_SQL / "inventario_unidades.sql")
_TRILHA_GLOBAL = consulta(_SQL / "trilha_auditoria_global.sql")
_TRILHA_ESCOPO = consulta(_SQL / "trilha_auditoria_escopo.sql")


class SqlConsultasDeRelatorio:
    """`ConsultasDeRelatorio` sobre o PostgreSQL, com o login da API (`sgs_app`)."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def lotes(
        self, tipo: str, filtros: Filtros, escopo: Escopo, *, tamanho: int = TAMANHO_DO_LOTE
    ) -> AsyncGenerator[list[Sequence[object]]]:
        if tipo == "inventario_unidades" and isinstance(filtros, FiltrosDoInventario):
            sql, parametros, linha = _INVENTARIO, _do_inventario(filtros, escopo), _inventario
        elif tipo == "trilha_auditoria" and isinstance(filtros, FiltrosDaTrilha):
            sql = _TRILHA_GLOBAL if escopo.global_ else _TRILHA_ESCOPO
            parametros, linha = _da_trilha(filtros, escopo), _trilha
        else:
            raise ValueError(f"filtros {type(filtros).__name__} não servem ao relatório {tipo}")

        async with self._engine.connect() as conexao, conexao.begin():
            await conexao.execute(_SOMENTE_LEITURA)
            resultado = await conexao.stream(sql, parametros)
            async for particao in resultado.partitions(tamanho):
                yield [linha(registro) for registro in particao]


def _do_inventario(filtros: FiltrosDoInventario, escopo: Escopo) -> dict[str, Any]:
    return parametros_de_escopo(escopo) | {
        "district_id": filtros.distrito_id,
        "technical_area_id": filtros.area_tecnica_id,
        "unit_type_id": filtros.tipo_unidade_id,
        "status": filtros.status,
    }


def _da_trilha(filtros: FiltrosDaTrilha, escopo: Escopo) -> dict[str, Any]:
    return parametros_de_escopo(escopo) | {
        "de": filtros.de,
        "ate": filtros.ate,
        "acao": filtros.acao,
        "entidade_tipo": filtros.entidade_tipo,
    }


def _inventario(registro: Row[Any]) -> Sequence[object]:
    """Na ordem de `COLUNAS_INVENTARIO_UNIDADES`."""
    return tuple(registro)


def _trilha(registro: Row[Any]) -> Sequence[object]:
    """Na ordem de `COLUNAS_TRILHA_AUDITORIA`: papéis numa célula só, mudanças em
    `campo: de → para`."""
    instante, acao, tipo_de_ator, autor, papeis, entidade, entidade_id, resultado, mudancas = tuple(
        registro
    )
    return (
        instante,
        acao,
        tipo_de_ator,
        autor,
        ", ".join(str(papel) for papel in papeis or ()),
        entidade,
        entidade_id,
        resultado,
        _mudancas(mudancas),
    )


def _mudancas(mudancas: Sequence[Mapping[str, Any]] | None) -> str:
    """Cada mudança como gravada (os valores pessoais já vêm `***`), separadas por `; `."""
    return "; ".join(
        f"{m.get('campo')}: {_valor(m.get('de'))} → {_valor(m.get('para'))}" for m in mudancas or ()
    )


def _valor(valor: object) -> str:
    if valor is None:
        return "—"
    if isinstance(valor, str):
        return valor
    return json.dumps(valor, ensure_ascii=False, sort_keys=True)
