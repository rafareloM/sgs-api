"""Repositórios do cadastro sobre a sessão SQLAlchemy de quem os usa.

SQL escrito à mão, em `sql/*.sql`, executado com `text()` e parâmetros nomeados (ADR-0009).
"""

from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import RowMapping, bindparam
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.sql import consulta
from src.modules.registry.domain.unidade import CAMPOS_DE_NEGOCIO, DadosDaUnidade, Unidade

_SQL = Path(__file__).parent / "sql"

# O JSONB declarado faz o SQLAlchemy serializar o dicionário do horário de funcionamento.
_INSERIR_UNIDADE = consulta(_SQL / "insert_health_unit.sql").bindparams(
    bindparam("opening_hours", type_=JSONB)
)
_AREA_DO_TIPO = consulta(_SQL / "unit_type_technical_area.sql")
_DISTRITO_ATIVO = consulta(_SQL / "district_is_active.sql")
_ID_PELO_CNES = consulta(_SQL / "health_unit_id_by_cnes.sql")
_ID_PELO_NOME = consulta(_SQL / "health_unit_id_by_name.sql")


class SqlRepositorioDeUnidades:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def area_do_tipo(self, unit_type_id: int) -> int | None:
        area: int | None = await self._session.scalar(_AREA_DO_TIPO, {"unit_type_id": unit_type_id})
        return area

    async def distrito_ativo(self, district_id: int) -> bool:
        return bool(await self._session.scalar(_DISTRITO_ATIVO, {"district_id": district_id}))

    async def inserir(self, id_: UUID, dados: DadosDaUnidade) -> Unidade | None:
        parametros: dict[str, Any] = {campo: getattr(dados, campo) for campo in CAMPOS_DE_NEGOCIO}
        resultado = await self._session.execute(_INSERIR_UNIDADE, {"id": id_, **parametros})
        linha = resultado.mappings().one_or_none()
        return None if linha is None else _unidade(linha)

    async def com_cnes(self, cnes: str) -> UUID | None:
        unidade: UUID | None = await self._session.scalar(_ID_PELO_CNES, {"cnes": cnes})
        return unidade

    async def com_nome(self, district_id: int, name: str) -> UUID | None:
        unidade: UUID | None = await self._session.scalar(
            _ID_PELO_NOME, {"district_id": district_id, "name": name}
        )
        return unidade


def _unidade(linha: RowMapping) -> Unidade:
    return Unidade(**dict(linha))
