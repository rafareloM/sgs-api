"""Registro da trilha de auditoria e hash encadeado (spec 001, R5.3).

hash = SHA-256(prev_hash || conteúdo canônico), em que o conteúdo canônico é o JSON do registro
com chaves ordenadas, sem espaços, em UTF-8 e com a data em UTC. Recalcular o hash a partir do
que está gravado revela qualquer adulteração.
"""

import hashlib
import ipaddress
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any, Self
from uuid import UUID

from src.core.errors import DomainValidationError, FieldError

GENESIS_HASH = "0" * 64

# Ações no formato recurso.verbo (steering/structure.md): unidade.atualizada, auth.login.
_ACTION = re.compile(r"[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*")
_HASH = re.compile(r"[0-9a-f]{64}")


def _freeze_json(value: Any, parents: set[int] | None = None) -> Any:
    if not isinstance(value, Mapping | list | tuple):
        return value
    parents = parents if parents is not None else set()
    identity = id(value)
    if identity in parents:
        raise _invalid("mudancas", "Os valores JSON não podem conter referências cíclicas.")
    parents.add(identity)
    try:
        if isinstance(value, Mapping):
            frozen = {key: _freeze_json(item, parents) for key, item in value.items()}
            return MappingProxyType(frozen)
        return tuple(_freeze_json(item, parents) for item in value)
    finally:
        parents.remove(identity)


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_thaw_json(item) for item in value]
    return value


@dataclass(frozen=True)
class Ator:
    """Quem fez a ação e de onde."""

    user_id: UUID | None = None
    papeis: tuple[str, ...] = ()
    session_id: UUID | None = None
    ip: str | None = None
    request_id: str | None = None

    def __post_init__(self) -> None:
        if self.ip is not None:
            try:
                normalized = str(ipaddress.ip_address(self.ip))
            except ValueError:
                raise _invalid("ip", "IP inválido.") from None
            object.__setattr__(self, "ip", normalized)


@dataclass(frozen=True)
class Entidade:
    tipo: str
    id: str


@dataclass(frozen=True)
class Mudanca:
    """Alteração de um campo; `de` e `para` precisam ser valores JSON."""

    campo: str
    de: Any
    para: Any

    def __post_init__(self) -> None:
        object.__setattr__(self, "de", _freeze_json(self.de))
        object.__setattr__(self, "para", _freeze_json(self.para))


@dataclass(frozen=True)
class AuditEntry:
    occurred_at: datetime
    action: str
    actor: Ator
    entity: Entidade | None
    changes: tuple[Mudanca, ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)
    prev_hash: str = GENESIS_HASH
    hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "changes", tuple(self.changes))
        object.__setattr__(self, "metadata", _freeze_json(dict(self.metadata)))

    @classmethod
    def create(
        cls,
        *,
        prev_hash: str,
        occurred_at: datetime,
        action: str,
        actor: Ator,
        entity: Entidade | None = None,
        changes: tuple[Mudanca, ...] = (),
        metadata: Mapping[str, Any] | None = None,
    ) -> Self:
        if occurred_at.tzinfo is None:
            raise _invalid("occurred_at", "Informe o fuso horário.")
        if len(action) > 100 or not _ACTION.fullmatch(action):
            raise _invalid("acao", "Use o formato recurso.verbo, em minúsculas.")
        if not _HASH.fullmatch(prev_hash):
            raise _invalid("prev_hash", "Hash anterior inválido.")
        draft = cls(
            occurred_at=occurred_at.astimezone(UTC),
            action=action,
            actor=actor,
            entity=entity,
            changes=tuple(changes),
            metadata=dict(metadata or {}),
            prev_hash=prev_hash,
        )
        return replace(draft, hash=draft.recompute_hash())

    def content(self) -> dict[str, Any]:
        """Conteúdo coberto pelo hash, só com tipos JSON."""
        return {
            "occurred_at": self.occurred_at.astimezone(UTC).isoformat(timespec="microseconds"),
            "actor_user_id": str(self.actor.user_id) if self.actor.user_id else None,
            "actor_roles": list(self.actor.papeis),
            "session_id": str(self.actor.session_id) if self.actor.session_id else None,
            "ip": self.actor.ip,
            "request_id": self.actor.request_id,
            "action": self.action,
            "entity_type": self.entity.tipo if self.entity else None,
            "entity_id": self.entity.id if self.entity else None,
            "changes": [
                {"campo": m.campo, "de": _thaw_json(m.de), "para": _thaw_json(m.para)}
                for m in self.changes
            ],
            "metadata": _thaw_json(self.metadata),
        }

    def canonical_content(self) -> bytes:
        try:
            text = json.dumps(
                self.content(),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
        except (TypeError, ValueError):
            raise _invalid("mudancas", "Os valores precisam ser JSON (sem NaN).") from None
        return text.encode("utf-8")

    def recompute_hash(self) -> str:
        return hashlib.sha256(self.prev_hash.encode("ascii") + self.canonical_content()).hexdigest()


def _invalid(campo: str, mensagem: str) -> DomainValidationError:
    return DomainValidationError(
        "Registro de auditoria inválido.", errors=[FieldError(campo=campo, mensagem=mensagem)]
    )
