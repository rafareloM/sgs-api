"""O que a API guarda do diretório: grupos espelhados e execuções da sincronização (spec 004,
design § Modelo de dados). Só stdlib; as tabelas ficam em `infrastructure/tables.py`."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

GROUP_NAME_MAX = 255
SYNC_ERROR_MAX = 200  # mensagem genérica, nunca o detalhe do erro (R1.10)

OrigemDeGrupo = Literal["ldap", "oidc"]
StatusDaExecucao = Literal["em_andamento", "concluida", "falhou"]
TipoDeConflito = Literal["email", "username"]


@dataclass(frozen=True)
class UpsertedGroup:
    id: UUID
    created: bool


@dataclass(frozen=True)
class GroupListing:
    """Grupo espelhado como o Admin TI o vê para mapear a um papel (R1.14)."""

    id: UUID
    source: OrigemDeGrupo
    name: str
    is_active: bool
    active_members: int


@dataclass(frozen=True)
class SyncCounts:
    users_created: int = 0
    users_updated: int = 0
    users_deactivated: int = 0
    groups_created: int = 0
    groups_updated: int = 0
    groups_deactivated: int = 0


@dataclass(frozen=True)
class SyncConflict:
    """Conta do diretório não criada porque o e-mail ou o `username` já é de outra (R4.2). Sem o
    e-mail nem o nome: o Admin TI chega à conta pelo id (LGPD)."""

    tipo: TipoDeConflito
    external_id: str
    # None quando a colisão é com outro usuário do mesmo retrato, que a sincronização cria.
    usuario_existente_id: UUID | None


@dataclass(frozen=True)
class SyncRun:
    id: UUID
    kind: Literal["ldap"]
    status: StatusDaExecucao
    started_at: datetime
    finished_at: datetime | None
    triggered_by: UUID | None  # nulo quando agendada
    counts: SyncCounts
    conflicts: tuple[SyncConflict, ...]
    error: str | None
