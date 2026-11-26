"""Conferência dos ids dos filtros do inventário (spec 005/T6; R1.5), em SQL escrito à mão."""

from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.sql import consulta
from src.modules.reports.domain.filtros import FiltrosDoInventario

_EXISTEM = consulta(Path(__file__).parent / "sql" / "referencias_dos_filtros.sql")


class SqlReferenciasDosFiltros:
    """`ReferenciasDosFiltros` sobre a sessão de quem a usa."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def inexistentes(self, filtros: FiltrosDoInventario) -> list[str]:
        linha = (
            (
                await self._session.execute(
                    _EXISTEM,
                    {
                        "district_id": filtros.distrito_id,
                        "technical_area_id": filtros.area_tecnica_id,
                        "unit_type_id": filtros.tipo_unidade_id,
                    },
                )
            )
            .mappings()
            .one()
        )
        return [campo for campo, existe in linha.items() if not existe]
