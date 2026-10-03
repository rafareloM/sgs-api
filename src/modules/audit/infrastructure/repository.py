"""AuditStore sobre a sessão SQLAlchemy de quem registra o evento."""

from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.audit.domain.entry import AuditEntry
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
