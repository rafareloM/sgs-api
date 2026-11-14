"""Repositório de equipamentos sobre a sessão SQLAlchemy de quem o usa (006/T7).

SQL escrito à mão, em `sql/*.sql`, executado com `text()` e parâmetros nomeados (ADR-0009).
"""

from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.sql import consulta
from src.modules.registry.domain.equipamento import (
    CAMPOS_DO_EQUIPAMENTO,
    DadosDoEquipamento,
    Equipamento,
)

_SQL = Path(__file__).parent / "sql"

_TIPO_ATIVO = consulta(_SQL / "equipment_type_is_active.sql")
_DA_UNIDADE = consulta(_SQL / "equipments_by_unit.sql")
_SEM_UNIDADE = consulta(_SQL / "equipments_without_unit.sql")
_PELO_ID = consulta(_SQL / "equipment_by_id.sql")
_INSERIR = consulta(_SQL / "insert_equipment.sql")
_ATUALIZAR = consulta(_SQL / "update_equipment.sql")
_REMOVER = consulta(_SQL / "delete_equipment.sql")


class SqlRepositorioDeEquipamentos:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def tipo_ativo(self, codigo: str) -> bool:
        return bool(await self._session.scalar(_TIPO_ATIVO, {"code": codigo}))

    async def da_unidade(self, unit_id: UUID) -> list[Equipamento]:
        resultado = await self._session.execute(_DA_UNIDADE, {"unit_id": unit_id})
        return [_equipamento(linha) for linha in resultado.mappings()]

    async def sem_unidade(self) -> list[Equipamento]:
        resultado = await self._session.execute(_SEM_UNIDADE)
        return [_equipamento(linha) for linha in resultado.mappings()]

    async def ler(self, id_: UUID) -> Equipamento | None:
        linha = (await self._session.execute(_PELO_ID, {"id": id_})).mappings().one_or_none()
        return None if linha is None else _equipamento(linha)

    async def inserir(
        self, id_: UUID, unit_id: UUID | None, dados: DadosDoEquipamento
    ) -> Equipamento:
        parametros = {"id": id_, "unit_id": unit_id, **_parametros(dados)}
        linha = (await self._session.execute(_INSERIR, parametros)).mappings().one()
        return _equipamento(linha)

    async def atualizar(self, id_: UUID, dados: DadosDoEquipamento) -> Equipamento | None:
        parametros = {"id": id_, **_parametros(dados)}
        linha = (await self._session.execute(_ATUALIZAR, parametros)).mappings().one_or_none()
        return None if linha is None else _equipamento(linha)

    async def remover(self, id_: UUID) -> bool:
        return (await self._session.scalar(_REMOVER, {"id": id_})) is not None


def _parametros(dados: DadosDoEquipamento) -> dict[str, Any]:
    return {campo: getattr(dados, campo) for campo in CAMPOS_DO_EQUIPAMENTO}


def _equipamento(linha: RowMapping) -> Equipamento:
    return Equipamento(**dict(linha))
