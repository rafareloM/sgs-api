"""Tabelas da auditoria: as da migração 0001_base, o índice da 0011_03 e o log da 0011_07."""

from sqlalchemy import (
    CHAR,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Identity,
    Index,
    SmallInteger,
    String,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

from src.core.db import metadata

audit_log = Table(
    "audit_log",
    metadata,
    Column("id", BigInteger, Identity(always=True), primary_key=True),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    Column("actor_user_id", Uuid, nullable=True),
    Column("actor_roles", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("session_id", Uuid, nullable=True),
    Column("ip", String(64), nullable=True),
    Column("request_id", String(128), nullable=True),
    Column("action", String(100), nullable=False),
    Column("entity_type", String(50), nullable=True),
    Column("entity_id", String(100), nullable=True),
    Column("changes", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("prev_hash", CHAR(64), nullable=False),
    Column("hash", CHAR(64), nullable=False),
    UniqueConstraint("hash"),
    UniqueConstraint("prev_hash"),
)

# Histórico de uma entidade, mais recente primeiro (migração 0011_03, spec 011 R1.1).
Index(
    "ix_audit_log_entity",
    audit_log.c.entity_type,
    audit_log.c.entity_id,
    audit_log.c.occurred_at.desc(),
)

audit_chain_head = Table(
    "audit_chain_head",
    metadata,
    Column("id", SmallInteger, primary_key=True, autoincrement=False),
    Column("last_hash", CHAR(64), nullable=False),
    CheckConstraint("id = 1", name="linha_unica"),
)

# Log do banco (migração 0011_07, spec 011 R7): gravado só pelo trigger `trg_registry_change_log`,
# com o `sgs_owner` como dono; a aplicação só lê. Particionado por mês: só a tabela-mãe fica aqui,
# as partições nascem no banco (`src.core.db.incluir_no_autogenerate`).
db_change_log = Table(
    "db_change_log",
    metadata,
    Column("id", BigInteger, Identity(always=True), primary_key=True),
    Column(
        "occurred_at",
        DateTime(timezone=True),
        primary_key=True,
        server_default=text("clock_timestamp()"),
    ),
    Column("table_name", Text, nullable=False),
    Column("operation", Text, nullable=False),
    Column("row_id", Uuid, nullable=False),
    Column("changed_columns", JSONB, nullable=False),
    Column("db_user", Text, nullable=False),
    Column("via_api", Boolean, nullable=False),
    Column("txid", BigInteger, nullable=False),
    CheckConstraint(
        "table_name IN ('health_units', 'equipments', 'services')", name="table_name_valido"
    ),
    CheckConstraint("operation IN ('INSERT', 'UPDATE', 'DELETE')", name="operation_valido"),
    postgresql_partition_by="RANGE (occurred_at)",
)

# Listagem do log por período, mais recente primeiro (spec 011 R7.7).
Index("ix_db_change_log_occurred_at", db_change_log.c.occurred_at.desc())
