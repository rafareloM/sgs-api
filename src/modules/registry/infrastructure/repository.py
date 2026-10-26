"""Repositórios SQLAlchemy para unidade de saúde e equipamento."""

from datetime import datetime

from sqlalchemy import RowMapping, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.registry.domain.equipamento import Equipamento
from src.modules.registry.domain.unidade import UnidadeSaude
from src.modules.registry.infrastructure.tables import equipamento as equipamento_table
from src.modules.registry.infrastructure.tables import unidade_saude as unidade_table


class SqlUnidadeSaudeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, entity: UnidadeSaude) -> UnidadeSaude:
        stmt = (
            insert(unidade_table)
            .values(
                codigocnes=entity.codigo_cnes,
                nome=entity.nome,
                tipo=entity.tipo,
                endereco=entity.endereco,
                cep=entity.cep,
                distritosanitario=entity.distrito_sanitario,
                telefone=entity.telefone,
                status=entity.status,
            )
            .returning(
                unidade_table.c.idunidade,
                unidade_table.c.datacriacao,
                unidade_table.c.dataatualizacao,
            )
        )
        result = await self._session.execute(stmt)
        row = result.mappings().one()
        return UnidadeSaude(
            id_unidade=row["idunidade"],
            codigo_cnes=entity.codigo_cnes,
            nome=entity.nome,
            tipo=entity.tipo,
            endereco=entity.endereco,
            cep=entity.cep,
            distrito_sanitario=entity.distrito_sanitario,
            telefone=entity.telefone,
            status=entity.status,
            data_criacao=row["datacriacao"],
            data_atualizacao=row["dataatualizacao"],
        )

    async def get_by_id(self, id_unidade: int) -> UnidadeSaude | None:
        stmt = select(unidade_table).where(unidade_table.c.idunidade == id_unidade)
        result = await self._session.execute(stmt)
        row = result.mappings().one_or_none()
        if row is None:
            return None
        return self._to_domain(row)

    async def get_by_cnes(self, codigo_cnes: str) -> UnidadeSaude | None:
        stmt = select(unidade_table).where(unidade_table.c.codigocnes == codigo_cnes)
        result = await self._session.execute(stmt)
        row = result.mappings().one_or_none()
        if row is None:
            return None
        return self._to_domain(row)

    async def list_all(self) -> list[UnidadeSaude]:
        stmt = select(unidade_table).order_by(unidade_table.c.idunidade)
        result = await self._session.execute(stmt)
        return [self._to_domain(row) for row in result.mappings().all()]

    def _to_domain(self, row: RowMapping) -> UnidadeSaude:
        return UnidadeSaude(
            id_unidade=int(row["idunidade"]),
            codigo_cnes=str(row["codigocnes"]),
            nome=str(row["nome"]),
            tipo=str(row["tipo"]),
            endereco=str(row["endereco"]),
            cep=str(row["cep"]),
            distrito_sanitario=str(row["distritosanitario"]),
            telefone=str(row["telefone"]) if row["telefone"] else None,
            status=str(row["status"]),
            data_criacao=row["datacriacao"] if isinstance(row["datacriacao"], datetime) else None,
            data_atualizacao=(
                row["dataatualizacao"] if isinstance(row["dataatualizacao"], datetime) else None
            ),
        )


class SqlEquipamentoRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, entity: Equipamento) -> Equipamento:
        stmt = (
            insert(equipamento_table)
            .values(
                nome=entity.nome,
                tipo=entity.tipo,
                quantidade=entity.quantidade,
                idunidade=entity.id_unidade,
            )
            .returning(equipamento_table.c.idequipamento)
        )
        result = await self._session.execute(stmt)
        inserted_id = result.scalar_one()
        return Equipamento(
            id_equipamento=inserted_id,
            nome=entity.nome,
            tipo=entity.tipo,
            quantidade=entity.quantidade,
            id_unidade=entity.id_unidade,
        )

    async def get_by_id(self, id_equipamento: int) -> Equipamento | None:
        stmt = select(equipamento_table).where(equipamento_table.c.idequipamento == id_equipamento)
        result = await self._session.execute(stmt)
        row = result.mappings().one_or_none()
        if row is None:
            return None
        return self._to_domain(row)

    async def list_by_unidade(self, id_unidade: int) -> list[Equipamento]:
        stmt = (
            select(equipamento_table)
            .where(equipamento_table.c.idunidade == id_unidade)
            .order_by(equipamento_table.c.idequipamento)
        )
        result = await self._session.execute(stmt)
        return [self._to_domain(row) for row in result.mappings().all()]

    def _to_domain(self, row: RowMapping) -> Equipamento:
        return Equipamento(
            id_equipamento=int(row["idequipamento"]),
            nome=str(row["nome"]),
            tipo=str(row["tipo"]),
            quantidade=int(row["quantidade"]),
            id_unidade=int(row["idunidade"]),
        )
