"""Tabelas de identidade, iguais às da migração 0002_identity."""

from datetime import datetime

from sqlalchemy import (
    CHAR,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Table,
    UniqueConstraint,
    Uuid,
    func,
    text,
)

from src.core.db import metadata
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
