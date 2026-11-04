"""Transformação de resultados das quatro consultas raw em JSON do dashboard."""

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, Mock

from sqlalchemy.sql.elements import TextClause

from src.modules.dashboard.infrastructure.repository import SqlDashboardRepository


def _result(rows: list[dict[str, Any]], one: dict[str, Any] | None = None) -> Mock:
    result = Mock()
    result.mappings.return_value.all.return_value = rows
    result.mappings.return_value.one.return_value = one or {}
    return result


async def test_resumo_executa_quatro_consultas_raw_com_escopo() -> None:
    session = AsyncMock()
    session.execute.side_effect = [
        _result(
            [
                {"categoria": "status", "chave": "Ativa", "total": 2},
                {"categoria": "tipo", "chave": "UBS", "total": 2},
                {"categoria": "distrito", "chave": "Centro", "total": 2},
                {"categoria": "sem_cnes", "chave": "sem_cnes", "total": 0},
                {"categoria": "total", "chave": "geral", "total": 2},
            ]
        ),
        _result([{"distrito": "Centro", "tipo": "Respirador", "registros": 1, "quantidade": 3}]),
        _result([], {"ultimos_7_dias": 1, "ultimos_30_dias": 4}),
        _result(
            [
                {
                    "idalteracao": 2,
                    "datahora": datetime(2026, 10, 26, 12, tzinfo=UTC),
                    "campoalterado": "Status",
                    "valoranterior": "Ativa",
                    "valornovo": "Inativa",
                    "idunidade": 3,
                    "unidade": "UBS São João",
                    "idusuario": 9,
                    "autor": "Ana",
                }
            ]
        ),
    ]
    repository = SqlDashboardRepository(session)

    result = await repository.resumo(distrito="Centro", id_unidade=3)

    assert session.execute.await_count == 4
    for call in session.execute.await_args_list:
        assert isinstance(call.args[0], TextClause)
        assert call.args[1] == {"distrito": "Centro", "id_unidade": 3}
    assert result["unidades"]["total"] == 2
    assert result["unidades"]["por_status"] == {"Ativa": 2}
    assert result["equipamentos"]["por_tipo_e_distrito"][0]["quantidade"] == 3
    assert result["alteracoes"]["ultimos_7_dias"] == 1
    assert result["alteracoes"]["recentes"][0]["autor"] == "Ana"
    assert result["qualidade"]["metricas_indisponiveis"] == [
        "area_tecnica",
        "pendencias",
        "servicos_fora_cnes",
    ]
