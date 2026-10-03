"""base: papel sgs_app, audit_log imutável e cabeça da cadeia de hash (spec 001, R5).

Revision ID: 0001
Revises:
Create Date: 2026-10-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GENESIS_HASH = "0" * 64


def upgrade() -> None:
    # Papel da aplicação, sem login próprio: o usuário com que a API conecta é membro dele.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'sgs_app') THEN
                CREATE ROLE sgs_app NOLOGIN;
            END IF;
        END
        $$
        """
    )
    op.execute("GRANT USAGE ON SCHEMA public TO sgs_app")
    # O que o dono criar daqui em diante já nasce com DML para sgs_app; as tabelas que fogem
    # disso (como a trilha de auditoria) revogam o que não cabe logo depois de criadas.
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public"
        " GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO sgs_app"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO sgs_app"
    )

    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_user_id", sa.Uuid, nullable=True),
        sa.Column("actor_roles", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("session_id", sa.Uuid, nullable=True),
        sa.Column("ip", sa.String(64), nullable=True),
        sa.Column("request_id", sa.String(128), nullable=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("entity_type", sa.String(50), nullable=True),
        sa.Column("entity_id", sa.String(100), nullable=True),
        sa.Column("changes", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("metadata", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("prev_hash", sa.CHAR(64), nullable=False),
        sa.Column("hash", sa.CHAR(64), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_audit_log"),
        sa.UniqueConstraint("hash", name="uq_audit_log_hash"),
        # Dois registros nunca apontam para o mesmo anterior: a cadeia não bifurca.
        sa.UniqueConstraint("prev_hash", name="uq_audit_log_prev_hash"),
    )
    chain_head = op.create_table(
        "audit_chain_head",
        sa.Column("id", sa.SmallInteger, nullable=False),
        sa.Column("last_hash", sa.CHAR(64), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_audit_chain_head"),
        sa.CheckConstraint("id = 1", name="ck_audit_chain_head_linha_unica"),
    )
    op.bulk_insert(chain_head, [{"id": 1, "last_hash": GENESIS_HASH}])

    op.execute(
        """
        CREATE FUNCTION audit_log_somente_insercao() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'audit_log é somente inserção: % bloqueado', TG_OP;
        END
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER audit_log_bloqueia_update_delete BEFORE UPDATE OR DELETE ON audit_log"
        " FOR EACH ROW EXECUTE FUNCTION audit_log_somente_insercao()"
    )
    op.execute(
        "CREATE TRIGGER audit_log_bloqueia_truncate BEFORE TRUNCATE ON audit_log"
        " FOR EACH STATEMENT EXECUTE FUNCTION audit_log_somente_insercao()"
    )
    # A API só insere e lê a trilha; a cabeça da cadeia ela só lê e atualiza.
    op.execute("REVOKE UPDATE, DELETE, TRUNCATE ON audit_log FROM sgs_app")
    op.execute("REVOKE INSERT, DELETE, TRUNCATE ON audit_chain_head FROM sgs_app")


def downgrade() -> None:
    op.drop_table("audit_chain_head")
    op.drop_table("audit_log")
    op.execute("DROP FUNCTION audit_log_somente_insercao()")
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE USAGE, SELECT ON SEQUENCES FROM sgs_app"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public"
        " REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM sgs_app"
    )
    op.execute("REVOKE USAGE ON SCHEMA public FROM sgs_app")
    # O papel sgs_app permanece: papéis valem para o servidor inteiro e podem ter
    # privilégios em outros bancos.
