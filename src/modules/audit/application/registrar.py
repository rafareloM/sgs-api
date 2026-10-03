"""Caso de uso `audit.registrar` (spec 001, R5.1 e R5.3).

Outros módulos chamam `registrar` dentro da própria transação, com um `AuditStore` ligado à
mesma sessão: se o caso de uso falhar, a auditoria é desfeita junto.
"""

from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from src.modules.audit.domain.entry import Ator, AuditEntry, Entidade, Mudanca
from src.modules.audit.domain.ports import AuditStore

# Reexportados para os outros módulos, que só importam a camada application da auditoria.
__all__ = ["Ator", "AuditEntry", "AuditStore", "Entidade", "Mudanca", "registrar"]


def _now() -> datetime:
    return datetime.now(UTC)


async def registrar(
    store: AuditStore,
    *,
    acao: str,
    ator: Ator,
    entidade: Entidade | None = None,
    mudancas: Sequence[Mudanca] = (),
    metadados: Mapping[str, Any] | None = None,
    agora: Callable[[], datetime] = _now,
) -> AuditEntry:
    """Grava o evento encadeado ao último registro. A trava da cabeça da cadeia serializa
    transações simultâneas, então a cadeia nunca bifurca."""
    prev_hash = await store.lock_chain_head()
    entry = AuditEntry.create(
        prev_hash=prev_hash,
        occurred_at=agora(),
        action=acao,
        actor=ator,
        entity=entidade,
        changes=tuple(mudancas),
        metadata=metadados,
    )
    await store.append(entry)
    return entry
