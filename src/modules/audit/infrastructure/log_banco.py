"""Leitura do log do banco em SQL escrito à mão (ADR-0009; design da 011 § Consultas).

Cada consulta está em `sql/<nome>.sql`, com o cabeçalho que a explica, e é lida uma vez, na carga
do módulo. Os filtros entram só como parâmetros nomeados: nenhum valor é interpolado no texto.
"""

from pathlib import Path
from typing import Any

from sqlalchemy import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.sql import consulta
from src.modules.audit.domain.historico import Pagina, Resultado
from src.modules.audit.domain.log_banco import AlteracaoBanco, FiltrosDoLog, ParticaoDoLog

_SQL = Path(__file__).parent / "sql"

_LISTAR = consulta(_SQL / "db_change_log_list.sql")
_PARTICOES = consulta(_SQL / "db_change_log_partitions.sql")


class SqlLogDoBanco:
    """`LogDoBanco` sobre a sessão SQLAlchemy de quem o consulta."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def listar(self, filtros: FiltrosDoLog, pagina: Pagina) -> Resultado[AlteracaoBanco]:
        parametros: dict[str, Any] = {
            "occurred_from": filtros.de,
            "occurred_to": filtros.ate,
            "table_name": filtros.tabela,
            "outside_api": filtros.fora_da_api,
            "limit": pagina.tamanho,
            "offset": pagina.offset,
        }
        linhas = (await self._session.execute(_LISTAR, parametros)).mappings().all()
        if linhas:
            total = int(linhas[0]["total"])
        elif pagina.offset == 0:
            total = 0
        else:
            # Página depois da última: o total sai da primeira.
            primeira = await self._session.execute(_LISTAR, {**parametros, "limit": 1, "offset": 0})
            linha = primeira.mappings().first()
            total = 0 if linha is None else int(linha["total"])
        return Resultado(itens=tuple(_alteracao(linha) for linha in linhas), total=total)

    async def particoes(self) -> tuple[ParticaoDoLog, ...]:
        linhas = (await self._session.execute(_PARTICOES)).mappings().all()
        return tuple(
            ParticaoDoLog(
                nome=linha["name"],
                de=linha["range_from"],
                ate=linha["range_to"],
                registros=int(linha["row_count"]),
            )
            for linha in linhas
        )


def _alteracao(linha: RowMapping) -> AlteracaoBanco:
    return AlteracaoBanco(
        ocorrido_em=linha["occurred_at"],
        tabela=linha["table_name"],
        operacao=linha["operation"],
        linha_id=linha["row_id"],
        colunas_alteradas=linha["changed_columns"],
        usuario_banco=linha["db_user"],
        via_api=linha["via_api"],
    )
