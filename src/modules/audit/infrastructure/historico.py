"""Histórico da unidade pela `vw_unit_history`, em SQL escrito à mão (ADR-0009; design da 011
§ Consultas de `audit/infrastructure/sql/`).

A consulta está em `sql/unit_history.sql`, com o cabeçalho que a explica, e é lida uma vez, na
carga do módulo. Unidade, filtros e página entram como parâmetros nomeados: nenhum valor é
interpolado no texto.
"""

from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.sql import consulta
from src.modules.audit.domain.historico import (
    EventoDoHistorico,
    FiltrosDoHistorico,
    MudancaNoHistorico,
    Pagina,
    Resultado,
)

_SQL = Path(__file__).parent / "sql"
_HISTORICO_DA_UNIDADE = consulta(_SQL / "unit_history.sql")


class SqlHistoricoDeUnidades:
    """`HistoricoDeUnidades` sobre a sessão SQLAlchemy de quem o usa."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def eventos(
        self, unidade_id: UUID, filtros: FiltrosDoHistorico, pagina: Pagina
    ) -> Resultado[EventoDoHistorico]:
        parametros: dict[str, Any] = {
            "unit_id": unidade_id,
            "occurred_from": filtros.de,
            "occurred_to": filtros.ate,
            "actor_user_id": filtros.autor,
            "changed_field": filtros.campo,
            "limit": pagina.tamanho,
            "offset": pagina.offset,
        }
        linhas = (await self._session.execute(_HISTORICO_DA_UNIDADE, parametros)).mappings().all()
        if linhas:
            total = int(linhas[0]["total"])
        elif pagina.offset == 0:
            total = 0
        else:
            # Página depois da última: o total sai da primeira.
            primeira = await self._session.execute(
                _HISTORICO_DA_UNIDADE, {**parametros, "limit": 1, "offset": 0}
            )
            linha = primeira.mappings().first()
            total = 0 if linha is None else int(linha["total"])
        return Resultado(itens=tuple(_evento(linha) for linha in linhas), total=total)


def _evento(linha: RowMapping) -> EventoDoHistorico:
    return EventoDoHistorico(
        id=linha["audit_id"],
        ocorrido_em=linha["occurred_at"],
        acao=linha["action"],
        autor_id=linha["actor_user_id"],
        autor_nome=linha["actor_name"],
        autor_papeis=tuple(linha["actor_roles"]),
        mudancas=tuple(
            MudancaNoHistorico(campo=m["campo"], de=m.get("de"), para=m.get("para"))
            for m in linha["changes"]
        ),
        metadados=dict(linha["metadata"]),
    )
