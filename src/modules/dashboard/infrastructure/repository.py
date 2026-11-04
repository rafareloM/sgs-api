"""Executa as consultas versionadas em consultas_etapa3.sql usando SQLAlchemy text()."""

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_SQL_FILE = Path(__file__).resolve().parents[4] / "consultas_etapa3.sql"
_QUERY_PATTERN = re.compile(r"(?ms)^-- consulta: ([a-z_]+)\s*\n(.*?)(?=^-- consulta: |\Z)")
_EXPECTED = {
    "unidades_por_categoria",
    "equipamentos_por_tipo_e_distrito",
    "alteracoes_por_periodo",
    "alteracoes_recentes",
}


def load_consultas() -> dict[str, Any]:
    conteudo = _SQL_FILE.read_text(encoding="utf-8")
    consultas = {nome: text(sql.strip()) for nome, sql in _QUERY_PATTERN.findall(conteudo)}
    if set(consultas) != _EXPECTED:
        raise RuntimeError("consultas_etapa3.sql deve conter as quatro consultas esperadas.")
    return consultas


_CONSULTAS = load_consultas()


def _data_recife(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(ZoneInfo("America/Recife")).isoformat()


class SqlDashboardRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def resumo(self, *, distrito: str | None, id_unidade: int | None) -> dict[str, Any]:
        filtros = {"distrito": distrito, "id_unidade": id_unidade}

        resultado_unidades = await self._session.execute(
            _CONSULTAS["unidades_por_categoria"], filtros
        )
        unidades = resultado_unidades.mappings().all()
        por_status = {
            row["chave"]: int(row["total"]) for row in unidades if row["categoria"] == "status"
        }
        por_tipo = [
            {"tipo": row["chave"], "total": int(row["total"])}
            for row in unidades
            if row["categoria"] == "tipo"
        ]
        por_distrito = [
            {"distrito": row["chave"], "total": int(row["total"])}
            for row in unidades
            if row["categoria"] == "distrito"
        ]
        total = next(int(row["total"]) for row in unidades if row["categoria"] == "total")
        sem_cnes = next(int(row["total"]) for row in unidades if row["categoria"] == "sem_cnes")

        resultado_equipamentos = await self._session.execute(
            _CONSULTAS["equipamentos_por_tipo_e_distrito"], filtros
        )
        por_equipamento = [
            {
                "distrito": row["distrito"],
                "tipo": row["tipo"],
                "registros": int(row["registros"]),
                "quantidade": int(row["quantidade"]),
            }
            for row in resultado_equipamentos.mappings().all()
        ]

        resultado_periodo = await self._session.execute(
            _CONSULTAS["alteracoes_por_periodo"], filtros
        )
        periodo = resultado_periodo.mappings().one()
        resultado_recentes = await self._session.execute(_CONSULTAS["alteracoes_recentes"], filtros)
        recentes = [
            {
                **dict(row),
                "datahora": _data_recife(row["datahora"]),
            }
            for row in resultado_recentes.mappings().all()
        ]

        return {
            "unidades": {
                "total": total,
                "por_status": por_status,
                "por_tipo": por_tipo,
                "por_area": None,
                "por_distrito": por_distrito,
            },
            "equipamentos": {"por_tipo_e_distrito": por_equipamento},
            "qualidade": {
                "unidades_com_pendencias": None,
                "total_pendencias": None,
                "sem_cnes": sem_cnes,
                "servicos_fora_cnes": None,
                "metricas_indisponiveis": ["area_tecnica", "pendencias", "servicos_fora_cnes"],
            },
            "alteracoes": {
                "ultimos_7_dias": int(periodo["ultimos_7_dias"]),
                "ultimos_30_dias": int(periodo["ultimos_30_dias"]),
                "recentes": recentes,
            },
            "gerado_em": datetime.now(ZoneInfo("America/Recife")).isoformat(),
        }
