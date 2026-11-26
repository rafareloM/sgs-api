"""Tabelas de identidade, iguais às das migrações 0002_identity e 0004_diretorio."""

from datetime import datetime

from sqlalchemy import (
    CHAR,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

from src.core.db import metadata
from src.modules.identity.domain.espelho_diretorio import GROUP_NAME_MAX, SYNC_ERROR_MAX
from src.modules.identity.domain.oidc import NONCE_MAX
from src.modules.identity.domain.sessions import AMR_MAX, USER_AGENT_MAX
from src.modules.identity.domain.users import (
    ARGON2ID_PHC,
    DISPLAY_NAME_MAX,
    EMAIL_MAX,
    EXTERNAL_ID_MAX,
    USERNAME_MAX,
)


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


users = Table(
    "users",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("username", String(USERNAME_MAX), nullable=False, unique=True),
    Column("email", String(EMAIL_MAX), nullable=True, unique=True),
    Column("display_name", String(DISPLAY_NAME_MAX), nullable=False),
    Column("password_hash", String(255), nullable=True),
    Column("source", String(10), nullable=False),
    Column("external_id", String(EXTERNAL_ID_MAX), nullable=True),
    Column("is_active", Boolean, nullable=False, server_default=text("true")),
    Column("mfa_enabled", Boolean, nullable=False, server_default=text("false")),
    Column("mfa_secret_enc", String(255), nullable=True),
    Column("mfa_last_step", BigInteger, nullable=True),
    # R2.6: `jti` do mfa_token mais recente e os códigos errados contra ele.
    Column("mfa_challenge_jti", Uuid, nullable=True),
    Column("mfa_failed_attempts", Integer, nullable=False, server_default=text("0")),
    Column("failed_logins", Integer, nullable=False, server_default=text("0")),
    Column("locked_until", DateTime(timezone=True), nullable=True),
    Column("last_login_at", DateTime(timezone=True), nullable=True),
    Column("synced_at", DateTime(timezone=True), nullable=True),
    # 003/R4.5: incrementada a cada alteração das atribuições; invalida o cache de permissões.
    Column("authz_version", Integer, nullable=False, server_default=text("0")),
    *_timestamps(),
    UniqueConstraint("source", "external_id"),
    CheckConstraint("source IN ('local', 'ldap', 'oidc')", name="origem_valida"),
    CheckConstraint("username = lower(username)", name="username_minusculo"),
    CheckConstraint("email = lower(email)", name="email_minusculo"),
    CheckConstraint(f"password_hash ~ '^{ARGON2ID_PHC.pattern}$'", name="senha_argon2id"),
    CheckConstraint(
        "(source = 'local' AND password_hash IS NOT NULL AND external_id IS NULL)"
        " OR (source <> 'local' AND password_hash IS NULL AND external_id IS NOT NULL)",
        name="credencial_conforme_origem",
    ),
    CheckConstraint("NOT mfa_enabled OR mfa_secret_enc IS NOT NULL", name="mfa_com_segredo"),
    CheckConstraint("failed_logins >= 0", name="falhas_nao_negativas"),
    CheckConstraint("mfa_failed_attempts >= 0", name="tentativas_mfa_nao_negativas"),
)

sessions = Table(
    "sessions",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("user_id", Uuid, ForeignKey("users.id"), nullable=False, index=True),
    Column("amr", String(AMR_MAX), nullable=False),
    Column("ip", String(64), nullable=True),
    Column("user_agent", String(USER_AGENT_MAX), nullable=True),
    *_timestamps(),
    Column("revoked_at", DateTime(timezone=True), nullable=True),
)

refresh_tokens = Table(
    "refresh_tokens",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("session_id", Uuid, ForeignKey("sessions.id"), nullable=False, index=True),
    Column("token_hash", CHAR(64), nullable=False, unique=True),
    Column("family_id", Uuid, nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("used_at", DateTime(timezone=True), nullable=True),
    Column("revoked_at", DateTime(timezone=True), nullable=True),
    *_timestamps(),
    CheckConstraint("token_hash ~ '^[0-9a-f]{64}$'", name="token_hash_sha256"),
)

# --- Spec 004: espelho do diretório e estado do login OIDC (migração 0004_diretorio)
_ORIGEM_EXTERNA = "source IN ('ldap', 'oidc')"

groups = Table(
    "groups",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("source", String(10), nullable=False),
    Column("external_id", String(EXTERNAL_ID_MAX), nullable=False),
    Column("name", String(GROUP_NAME_MAX), nullable=False),
    Column("description", String(1024), nullable=True),
    # Nunca apagado, só desativado: mantém as FKs dos mapeamentos da 003.
    Column("is_active", Boolean, nullable=False, server_default=text("true")),
    Column("synced_at", DateTime(timezone=True), nullable=True),
    *_timestamps(),
    UniqueConstraint("source", "external_id"),
    CheckConstraint(_ORIGEM_EXTERNA, name="origem_valida"),
)

user_groups = Table(
    "user_groups",
    metadata,
    Column("user_id", Uuid, ForeignKey("users.id"), primary_key=True),
    Column("group_id", Uuid, ForeignKey("groups.id"), primary_key=True, index=True),
    Column("source", String(10), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint(_ORIGEM_EXTERNA, name="origem_valida"),
)

SYNC_COUNT_COLUMNS = (
    "users_created",
    "users_updated",
    "users_deactivated",
    "groups_created",
    "groups_updated",
    "groups_deactivated",
)

directory_sync_runs = Table(
    "directory_sync_runs",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("kind", String(10), nullable=False),
    Column("status", String(15), nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=False, index=True),
    Column("finished_at", DateTime(timezone=True), nullable=True),
    Column("triggered_by", Uuid, ForeignKey("users.id"), nullable=True),
    *(
        Column(nome, Integer, nullable=False, server_default=text("0"))
        for nome in SYNC_COUNT_COLUMNS
    ),
    Column("conflicts", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("error", String(SYNC_ERROR_MAX), nullable=True),
    CheckConstraint("kind IN ('ldap')", name="tipo_valido"),
    CheckConstraint("status IN ('em_andamento', 'concluida', 'falhou')", name="status_valido"),
    CheckConstraint(
        "(status = 'em_andamento') = (finished_at IS NULL)", name="fim_conforme_status"
    ),
    CheckConstraint(
        " AND ".join(f"{nome} >= 0" for nome in SYNC_COUNT_COLUMNS), name="contagens_nao_negativas"
    ),
    CheckConstraint("jsonb_typeof(conflicts) = 'array'", name="conflitos_em_lista"),
    # Uma execução em andamento por vez (R1.11, D004-1).
    Index(
        "ux_directory_sync_runs_em_andamento",
        "kind",
        unique=True,
        postgresql_where=text("status = 'em_andamento'"),
    ),
)

oidc_login_requests = Table(
    "oidc_login_requests",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("state_hash", CHAR(64), nullable=False, unique=True),
    Column("binding_hash", CHAR(64), nullable=False),
    Column("nonce", String(NONCE_MAX), nullable=False),
    Column("code_verifier_enc", String(255), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("used_at", DateTime(timezone=True), nullable=True),
    CheckConstraint("state_hash ~ '^[0-9a-f]{64}$'", name="state_hash_sha256"),
    CheckConstraint("binding_hash ~ '^[0-9a-f]{64}$'", name="binding_hash_sha256"),
    CheckConstraint("expires_at > created_at", name="vence_depois_de_criar"),
)
