"""Tabelas da auditoria, iguais às da migração 0001_base."""

from sqlalchemy import (
    CHAR,
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    SmallInteger,
    String,
    Table,
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

audit_chain_head = Table(
    "audit_chain_head",
    metadata,
    Column("id", SmallInteger, primary_key=True, autoincrement=False),
    Column("last_hash", CHAR(64), nullable=False),
    CheckConstraint("id = 1", name="linha_unica"),
)

alteracao = Table(
    "alteracao",
    metadata,
    Column("idalteracao", Integer, Identity(always=True), primary_key=True),
    Column("datahora", DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    Column("campoalterado", String(50), nullable=False),
    Column("valoranterior", String(255), nullable=True),
    Column("valornovo", String(255), nullable=True),
    Column(
        "idunidade",
        Integer,
        ForeignKey(
            "unidade_saude.idunidade",
            onupdate="CASCADE",
            name="fk_alteracao_idunidade_unidade_saude",
        ),
        nullable=False,
    ),
    Column(
        "idusuario",
        Integer,
        ForeignKey(
            "usuario.idusuario",
            onupdate="CASCADE",
            name="fk_alteracao_idusuario_usuario",
        ),
        nullable=False,
    ),
    CheckConstraint("btrim(campoalterado) <> ''", name="ck_alteracao_campoalterado_nao_vazio"),
    CheckConstraint(
        "valoranterior IS NOT NULL OR valornovo IS NOT NULL",
        name="ck_alteracao_valores_nao_ambos_nulos",
    ),
)
