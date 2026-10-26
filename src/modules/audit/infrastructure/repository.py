"""AuditStore sobre a sessão SQLAlchemy de quem registra o evento."""

from datetime import datetime

from sqlalchemy import RowMapping, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.audit.domain.alteracao import Alteracao
from src.modules.audit.domain.entry import AuditEntry
from src.modules.audit.infrastructure.tables import alteracao as alteracao_table
from src.modules.audit.infrastructure.tables import audit_chain_head, audit_log


class SqlAuditStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def lock_chain_head(self) -> str:
        # SELECT ... FOR UPDATE: outra transação que for registrar espera esta terminar.
        last_hash = await self._session.scalar(
            select(audit_chain_head.c.last_hash).where(audit_chain_head.c.id == 1).with_for_update()
        )
        if last_hash is None:
            raise RuntimeError("audit_chain_head sem a linha inicial; rode as migrações.")
        return str(last_hash)

    async def append(self, entry: AuditEntry) -> None:
        if entry.recompute_hash() != entry.hash:
            raise ValueError("O hash do registro de auditoria não corresponde ao conteúdo.")
        content = entry.content()
        await self._session.execute(
            insert(audit_log).values(
                occurred_at=entry.occurred_at,
                actor_user_id=entry.actor.user_id,
                actor_roles=content["actor_roles"],
                session_id=entry.actor.session_id,
                ip=entry.actor.ip,
                request_id=entry.actor.request_id,
                action=entry.action,
                entity_type=content["entity_type"],
                entity_id=content["entity_id"],
                changes=content["changes"],
                metadata=content["metadata"],
                prev_hash=entry.prev_hash,
                hash=entry.hash,
            )
        )
        await self._session.execute(
            update(audit_chain_head).where(audit_chain_head.c.id == 1).values(last_hash=entry.hash)
        )


class SqlAlteracaoRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, entity: Alteracao) -> Alteracao:
        stmt = (
            insert(alteracao_table)
            .values(
                campoalterado=entity.campo_alterado,
                valoranterior=entity.valor_anterior,
                valornovo=entity.valor_novo,
                idunidade=entity.id_unidade,
                idusuario=entity.id_usuario,
            )
            .returning(
                alteracao_table.c.idalteracao,
                alteracao_table.c.datahora,
            )
        )
        result = await self._session.execute(stmt)
        row = result.mappings().one()
        return Alteracao(
            id_alteracao=row["idalteracao"],
            data_hora=row["datahora"],
            campo_alterado=entity.campo_alterado,
            valor_anterior=entity.valor_anterior,
            valor_novo=entity.valor_novo,
            id_unidade=entity.id_unidade,
            id_usuario=entity.id_usuario,
        )

    async def get_by_id(self, id_alteracao: int) -> Alteracao | None:
        stmt = select(alteracao_table).where(alteracao_table.c.idalteracao == id_alteracao)
        result = await self._session.execute(stmt)
        row = result.mappings().one_or_none()
        if row is None:
            return None
        return self._to_domain(row)

    async def list_by_unidade(self, id_unidade: int) -> list[Alteracao]:
        stmt = (
            select(alteracao_table)
            .where(alteracao_table.c.idunidade == id_unidade)
            .order_by(alteracao_table.c.idalteracao)
        )
        result = await self._session.execute(stmt)
        return [self._to_domain(row) for row in result.mappings().all()]

    def _to_domain(self, row: RowMapping) -> Alteracao:
        val_ant = str(row["valoranterior"]) if row["valoranterior"] is not None else None
        val_novo = str(row["valornovo"]) if row["valornovo"] is not None else None
        return Alteracao(
            id_alteracao=int(row["idalteracao"]),
            data_hora=row["datahora"] if isinstance(row["datahora"], datetime) else None,
            campo_alterado=str(row["campoalterado"]),
            valor_anterior=val_ant,
            valor_novo=val_novo,
            id_unidade=int(row["idunidade"]),
            id_usuario=int(row["idusuario"]),
        )
