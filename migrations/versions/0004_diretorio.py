"""identity: espelho do diretório e estado do login OIDC (spec 004, T1).

- `groups` e `user_groups`: grupos espelhados do LDAP e do OIDC e as associações (R1.8, R1.14);
- `directory_sync_runs`, com uma execução em andamento por vez (R1.9, R1.11, D004-1);
- `oidc_login_requests`: `state` de uso único (R3.7, D004-2);
- FK de `group_role_mappings.group_id` → `groups.id`, só se não houver `group_id` órfão.

Revision ID: 0004
Revises: 0013_04
Create Date: 2026-11-25
"""

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0013_04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EXTERNAL_ID_MAX = 512  # identity/domain/users.py
ORIGEM_EXTERNA = "source IN ('ldap', 'oidc')"
CONTAGENS = (
    "users_created",
    "users_updated",
    "users_deactivated",
    "groups_created",
    "groups_updated",
    "groups_deactivated",
)


def _agora(nome: str) -> "sa.Column[datetime]":
    return sa.Column(nome, sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


def _conferir_mapeamentos_orfaos() -> None:
    if op.get_context().as_sql:
        return  # modo offline (`--sql`): não há banco para conferir; a própria FK recusa órfãos
    orfaos = op.get_bind().scalar(
        sa.text(
            "SELECT count(*) FROM group_role_mappings m"
            " WHERE NOT EXISTS (SELECT 1 FROM groups g WHERE g.id = m.group_id)"
        )
    )
    if orfaos:
        raise RuntimeError(
            f"0004_diretorio: {orfaos} linha(s) de group_role_mappings com group_id órfão"
            " (sem grupo em `groups`). Apague ou corrija esses mapeamentos e rode a migração de"
            " novo; a FK group_role_mappings.group_id → groups.id não entra com órfãos."
        )


def upgrade() -> None:
    op.create_table(
        "groups",
        sa.Column("id", sa.Uuid, nullable=False),
        sa.Column("source", sa.String(10), nullable=False),
        sa.Column("external_id", sa.String(EXTERNAL_ID_MAX), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.String(1024), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True),
        _agora("created_at"),
        _agora("updated_at"),
        sa.PrimaryKeyConstraint("id", name="pk_groups"),
        sa.UniqueConstraint("source", "external_id", name="uq_groups_source_external_id"),
        sa.CheckConstraint(ORIGEM_EXTERNA, name=op.f("ck_groups_origem_valida")),
    )
    op.create_table(
        "user_groups",
        sa.Column("user_id", sa.Uuid, nullable=False),
        sa.Column("group_id", sa.Uuid, nullable=False),
        sa.Column("source", sa.String(10), nullable=False),
        _agora("created_at"),
        sa.PrimaryKeyConstraint("user_id", "group_id", name="pk_user_groups"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_user_groups_user_id_users"),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], name="fk_user_groups_group_id_groups"),
        sa.CheckConstraint(ORIGEM_EXTERNA, name=op.f("ck_user_groups_origem_valida")),
    )
    op.create_index("ix_user_groups_group_id", "user_groups", ["group_id"])

    op.create_table(
        "directory_sync_runs",
        sa.Column("id", sa.Uuid, nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("status", sa.String(15), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("triggered_by", sa.Uuid, nullable=True),
        *(
            sa.Column(nome, sa.Integer, nullable=False, server_default=sa.text("0"))
            for nome in CONTAGENS
        ),
        sa.Column(
            "conflicts",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("error", sa.String(200), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_directory_sync_runs"),
        sa.ForeignKeyConstraint(
            ["triggered_by"], ["users.id"], name="fk_directory_sync_runs_triggered_by_users"
        ),
        sa.CheckConstraint("kind IN ('ldap')", name=op.f("ck_directory_sync_runs_tipo_valido")),
        sa.CheckConstraint(
            "status IN ('em_andamento', 'concluida', 'falhou')",
            name=op.f("ck_directory_sync_runs_status_valido"),
        ),
        sa.CheckConstraint(
            "(status = 'em_andamento') = (finished_at IS NULL)",
            name=op.f("ck_directory_sync_runs_fim_conforme_status"),
        ),
        sa.CheckConstraint(
            " AND ".join(f"{nome} >= 0" for nome in CONTAGENS),
            name=op.f("ck_directory_sync_runs_contagens_nao_negativas"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(conflicts) = 'array'",
            name=op.f("ck_directory_sync_runs_conflitos_em_lista"),
        ),
    )
    op.create_index("ix_directory_sync_runs_started_at", "directory_sync_runs", ["started_at"])
    # R1.11, D004-1: uma execução em andamento por vez, garantida pelo banco.
    op.create_index(
        "ux_directory_sync_runs_em_andamento",
        "directory_sync_runs",
        ["kind"],
        unique=True,
        postgresql_where=sa.text("status = 'em_andamento'"),
    )

    op.create_table(
        "oidc_login_requests",
        sa.Column("id", sa.Uuid, nullable=False),
        sa.Column("state_hash", sa.CHAR(64), nullable=False),
        sa.Column("binding_hash", sa.CHAR(64), nullable=False),
        sa.Column("nonce", sa.String(64), nullable=False),
        sa.Column("code_verifier_enc", sa.String(255), nullable=False),
        _agora("created_at"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_oidc_login_requests"),
        sa.UniqueConstraint("state_hash", name="uq_oidc_login_requests_state_hash"),
        sa.CheckConstraint(
            "state_hash ~ '^[0-9a-f]{64}$'", name=op.f("ck_oidc_login_requests_state_hash_sha256")
        ),
        sa.CheckConstraint(
            "binding_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_oidc_login_requests_binding_hash_sha256"),
        ),
        sa.CheckConstraint(
            "expires_at > created_at", name=op.f("ck_oidc_login_requests_vence_depois_de_criar")
        ),
    )

    _conferir_mapeamentos_orfaos()
    op.create_foreign_key(
        "fk_group_role_mappings_group_id_groups",
        "group_role_mappings",
        "groups",
        ["group_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_group_role_mappings_group_id_groups", "group_role_mappings", type_="foreignkey"
    )
    op.drop_table("oidc_login_requests")
    op.drop_table("directory_sync_runs")
    op.drop_table("user_groups")
    op.drop_table("groups")
