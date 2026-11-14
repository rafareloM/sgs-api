"""Repositório das tabelas de referência sobre a sessão SQLAlchemy de quem o usa.

Uma consulta por tabela e operação, em `sql/*.sql` (ADR-0009): o nome da tabela nunca entra
por interpolação, só os valores, como parâmetros nomeados.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import RowMapping, TextClause
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.sql import consulta
from src.modules.registry.domain.referencia import (
    Alteracao,
    CodigoRepetidoError,
    DadosDaReferencia,
    Referencia,
    TipoDeReferencia,
)

_SQL = Path(__file__).parent / "sql"

# SQLSTATE de violação de unicidade (o código do item, `uq_<tabela>_code`).
_VIOLACAO_DE_UNICIDADE = "23505"

# Campo da API → coluna do banco (parâmetro das consultas).
_COLUNAS = {
    "codigo": "code",
    "nome": "name",
    "ativo": "is_active",
    "area_tecnica_id": "technical_area_id",
}


@dataclass(frozen=True)
class _Consultas:
    listar: TextClause
    inserir: TextClause
    atualizar: TextClause


def _consultas(tabela: str, singular: str) -> _Consultas:
    return _Consultas(
        listar=consulta(_SQL / f"select_{tabela}.sql"),
        inserir=consulta(_SQL / f"insert_{singular}.sql"),
        atualizar=consulta(_SQL / f"update_{singular}.sql"),
    )


_POR_TIPO = {
    TipoDeReferencia.DISTRITO: _consultas("districts", "district"),
    TipoDeReferencia.AREA_TECNICA: _consultas("technical_areas", "technical_area"),
    TipoDeReferencia.TIPO_UNIDADE: _consultas("unit_types", "unit_type"),
    TipoDeReferencia.TIPO_EQUIPAMENTO: _consultas("equipment_types", "equipment_type"),
    TipoDeReferencia.TIPO_SERVICO: _consultas("service_types", "service_type"),
}
_AREA_ATIVA = consulta(_SQL / "technical_area_is_active.sql")
_EQUIPAMENTOS_DO_TIPO = consulta(_SQL / "equipments_count_by_type_code.sql")


class SqlRepositorioDeReferencias:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def listar(self, tipo: TipoDeReferencia) -> list[Referencia]:
        resultado = await self._session.execute(_POR_TIPO[tipo].listar)
        return [_referencia(linha) for linha in resultado.mappings()]

    async def area_ativa(self, area_tecnica_id: int) -> bool:
        return bool(await self._session.scalar(_AREA_ATIVA, {"technical_area_id": area_tecnica_id}))

    async def inserir(self, tipo: TipoDeReferencia, dados: DadosDaReferencia) -> Referencia | None:
        parametros: dict[str, Any] = {"code": dados.codigo, "name": dados.nome}
        if tipo is TipoDeReferencia.TIPO_UNIDADE:
            parametros["technical_area_id"] = dados.area_tecnica_id
        resultado = await self._session.execute(_POR_TIPO[tipo].inserir, parametros)
        linha = resultado.mappings().one_or_none()
        return None if linha is None else _referencia(linha)

    async def atualizar(
        self, tipo: TipoDeReferencia, id_: int, mudancas: dict[str, object]
    ) -> Alteracao | None:
        parametros: dict[str, Any] = {"id": id_, "code": None, "name": None, "is_active": None}
        if tipo is TipoDeReferencia.TIPO_UNIDADE:
            parametros["technical_area_id"] = None
        parametros.update({_COLUNAS[campo]: valor for campo, valor in mudancas.items()})
        try:
            # Ponto de salvamento: o código repetido desfaz só o UPDATE, não a transação.
            async with self._session.begin_nested():
                resultado = await self._session.execute(_POR_TIPO[tipo].atualizar, parametros)
                linha = resultado.mappings().one_or_none()
        except IntegrityError as erro:
            if getattr(erro.orig, "sqlstate", None) == _VIOLACAO_DE_UNICIDADE:
                raise CodigoRepetidoError from None
            raise
        if linha is None:
            return None
        antes = Referencia(
            id=linha["id"],
            codigo=linha["previous_code"],
            nome=linha["previous_name"],
            ativo=linha["previous_is_active"],
            area_tecnica_id=linha.get("previous_technical_area_id"),
        )
        return Alteracao(antes=antes, depois=_referencia(linha))

    async def equipamentos_do_tipo(self, codigo: str) -> int:
        return int(await self._session.scalar(_EQUIPAMENTOS_DO_TIPO, {"code": codigo}) or 0)


def _referencia(linha: RowMapping) -> Referencia:
    return Referencia(
        id=linha["id"],
        codigo=linha["code"],
        nome=linha["name"],
        ativo=linha["is_active"],
        area_tecnica_id=linha.get("technical_area_id"),
    )
