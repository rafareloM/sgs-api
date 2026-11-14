"""Repositório de serviços sobre a sessão SQLAlchemy de quem o usa (006/T8).

SQL escrito à mão, em `sql/*.sql`, executado com `text()` e parâmetros nomeados (ADR-0009).
"""

from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.sql import consulta
from src.modules.registry.domain.servico import CAMPOS_DO_SERVICO, DadosDoServico, Servico

_SQL = Path(__file__).parent / "sql"

_TIPO_ATIVO = consulta(_SQL / "service_type_is_active.sql")
_EQUIPAMENTO_NA_UNIDADE = consulta(_SQL / "equipment_in_unit.sql")
SERVICOS_DA_UNIDADE = consulta(_SQL / "services_by_unit.sql")
_SOLTOS = consulta(_SQL / "services_without_unit.sql")
_PELO_ID = consulta(_SQL / "service_by_id.sql")
_INSERIR = consulta(_SQL / "insert_service.sql")
_ATUALIZAR = consulta(_SQL / "update_service.sql")
_REMOVER = consulta(_SQL / "delete_service.sql")


class SqlRepositorioDeServicos:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def tipo_ativo(self, tipo_id: int) -> bool:
        return bool(await self._session.scalar(_TIPO_ATIVO, {"id": tipo_id}))

    async def equipamento_na_unidade(self, equipamento_id: UUID, unit_id: UUID | None) -> bool:
        parametros = {"equipment_id": equipamento_id, "unit_id": unit_id}
        return bool(await self._session.scalar(_EQUIPAMENTO_NA_UNIDADE, parametros))

    async def da_unidade(self, unit_id: UUID) -> list[Servico]:
        resultado = await self._session.execute(SERVICOS_DA_UNIDADE, {"unit_id": unit_id})
        return [_servico(linha) for linha in resultado.mappings()]

    async def soltos(self) -> list[Servico]:
        resultado = await self._session.execute(_SOLTOS)
        return [_servico(linha) for linha in resultado.mappings()]

    async def ler(self, id_: UUID) -> Servico | None:
        linha = (await self._session.execute(_PELO_ID, {"id": id_})).mappings().one_or_none()
        return None if linha is None else _servico(linha)

    async def inserir(self, id_: UUID, unit_id: UUID | None, dados: DadosDoServico) -> Servico:
        parametros = {"id": id_, "unit_id": unit_id, **_parametros(dados)}
        linha = (await self._session.execute(_INSERIR, parametros)).mappings().one()
        return _servico(linha)

    async def atualizar(self, id_: UUID, dados: DadosDoServico) -> Servico | None:
        parametros = {"id": id_, **_parametros(dados)}
        linha = (await self._session.execute(_ATUALIZAR, parametros)).mappings().one_or_none()
        return None if linha is None else _servico(linha)

    async def remover(self, id_: UUID) -> bool:
        return (await self._session.scalar(_REMOVER, {"id": id_})) is not None


def _parametros(dados: DadosDoServico) -> dict[str, Any]:
    return {campo: getattr(dados, campo) for campo in CAMPOS_DO_SERVICO}


def _servico(linha: RowMapping) -> Servico:
    return Servico(**dict(linha))
