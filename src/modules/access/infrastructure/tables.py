"""Tabelas do RBAC com escopo, iguais às da migração 0003_access."""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    String,
    Table,
    Uuid,
    func,
    text,
)

from src.core.db import metadata

# Níveis de escopo (003/R1.2), do mais amplo ao mais restrito.
ESCOPOS = ("global", "area", "distrito", "unidade")


def _timestamps() -> tuple[Column[datetime], Column[datetime]]:
    return (
        Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
        Column(
            "updated_at",
            DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
            onupdate=func.now(),
        ),
    )


roles = Table(
    "roles",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("code", String(50), nullable=False, unique=True),
    Column("name", String(100), nullable=False),
    Column("description", String(500), nullable=False),
    Column("is_system", Boolean, nullable=False, server_default=text("false")),
    *_timestamps(),
)

permissions = Table(
    "permissions",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("code", String(100), nullable=False, unique=True),
    Column("description", String(500), nullable=False),
    *_timestamps(),
)

role_permissions = Table(
    "role_permissions",
    metadata,
    Column("role_id", Uuid, ForeignKey("roles.id"), primary_key=True),
    Column("permission_id", Uuid, ForeignKey("permissions.id"), primary_key=True),
    Column("max_scope", String(10), nullable=False),
    *_timestamps(),
    CheckConstraint(f"max_scope IN {ESCOPOS}", name="escopo_maximo_valido"),
)

# `scope_id` guarda o id do distrito, da área técnica (smallint) ou da unidade (uuid), em texto;
# nulo quando o escopo é global (modelo-dados.md § 1).
_ESCOPO_VALIDO = f"scope_type IN {ESCOPOS}"
_ESCOPO_CONFORME_TIPO = "(scope_type = 'global') = (scope_id IS NULL)"

group_role_mappings = Table(
    "group_role_mappings",
    metadata,
    Column("id", Uuid, primary_key=True),
    # Sem FK por enquanto: a tabela `groups` nasce na spec 004 (T1).
    Column("group_id", Uuid, nullable=False),
    Column("role_id", Uuid, ForeignKey("roles.id"), nullable=False),
    Column("scope_type", String(10), nullable=False),
    Column("scope_id", String(36), nullable=True),
    Column("created_by", Uuid, ForeignKey("users.id"), nullable=False),
    *_timestamps(),
    CheckConstraint(_ESCOPO_VALIDO, name="escopo_valido"),
    CheckConstraint(_ESCOPO_CONFORME_TIPO, name="escopo_conforme_tipo"),
)

role_assignments = Table(
    "role_assignments",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("user_id", Uuid, ForeignKey("users.id"), nullable=False, index=True),
    Column("role_id", Uuid, ForeignKey("roles.id"), nullable=False),
    Column("scope_type", String(10), nullable=False),
    Column("scope_id", String(36), nullable=True),
    Column("origin", String(10), nullable=False),
    Column("group_mapping_id", Uuid, ForeignKey("group_role_mappings.id"), nullable=True),
    Column("granted_by", Uuid, ForeignKey("users.id"), nullable=True),
    Column("valid_until", DateTime(timezone=True), nullable=True),
    *_timestamps(),
    CheckConstraint(_ESCOPO_VALIDO, name="escopo_valido"),
    CheckConstraint(_ESCOPO_CONFORME_TIPO, name="escopo_conforme_tipo"),
    CheckConstraint("origin IN ('direct', 'group')", name="origem_valida"),
    # Atribuição derivada aponta o mapeamento que a gerou; a direta não aponta nenhum.
    CheckConstraint(
        "(origin = 'group') = (group_mapping_id IS NOT NULL)", name="origem_conforme_mapeamento"
    ),
)
