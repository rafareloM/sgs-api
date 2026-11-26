"""Repositórios de identidade sobre a sessão SQLAlchemy de quem os usa (SQLAlchemy Core)."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import case, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.identity.domain.login import (
    DURACAO_DO_BLOQUEIO,
    FALHAS_PARA_BLOQUEIO,
    TENTATIVAS_DE_MFA,
    EstadoDeLogin,
)
from src.modules.identity.domain.sessions import AuthSession, RefreshToken
from src.modules.identity.domain.users import User, UserSource, normalize_username
from src.modules.identity.infrastructure.tables import refresh_tokens, sessions, users

# Só as colunas que o `User` conhece; o segredo TOTP fica de fora até a T5.
_USER_COLUMNS = (
    users.c.id,
    users.c.username,
    users.c.display_name,
    users.c.source,
    users.c.password_hash,
    users.c.email,
    users.c.external_id,
    users.c.is_active,
)
_SESSION_COLUMNS = (
    sessions.c.id,
    sessions.c.user_id,
    sessions.c.amr,
    sessions.c.created_at,
    sessions.c.ip,
    sessions.c.user_agent,
    sessions.c.revoked_at,
)
_REFRESH_COLUMNS = (
    refresh_tokens.c.id,
    refresh_tokens.c.session_id,
    refresh_tokens.c.family_id,
    refresh_tokens.c.token_hash,
    refresh_tokens.c.expires_at,
    refresh_tokens.c.used_at,
    refresh_tokens.c.revoked_at,
)


class SqlUserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, user: User) -> None:
        await self._session.execute(
            insert(users).values(
                id=user.id,
                username=user.username,
                display_name=user.display_name,
                source=user.source.value,
                password_hash=user.password_hash,
                email=user.email,
                external_id=user.external_id,
                is_active=user.is_active,
            )
        )

    async def get_by_id(self, user_id: UUID) -> User | None:
        result = await self._session.execute(select(*_USER_COLUMNS).where(users.c.id == user_id))
        row = result.mappings().one_or_none()
        return None if row is None else User(**row)

    async def get_by_username(self, username: str) -> User | None:
        result = await self._session.execute(
            select(*_USER_COLUMNS).where(users.c.username == normalize_username(username))
        )
        row = result.mappings().one_or_none()
        return None if row is None else User(**row)

    async def get_by_email(self, email: str) -> User | None:
        result = await self._session.execute(
            select(*_USER_COLUMNS).where(users.c.email == email.strip().lower())
        )
        row = result.mappings().one_or_none()
        return None if row is None else User(**row)

    async def get_by_external_id(self, source: UserSource, external_id: str) -> User | None:
        result = await self._session.execute(
            select(*_USER_COLUMNS).where(
                users.c.source == source.value, users.c.external_id == external_id
            )
        )
        row = result.mappings().one_or_none()
        return None if row is None else User(**row)


class SqlSessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, session: AuthSession) -> None:
        await self._session.execute(
            insert(sessions).values(
                id=session.id,
                user_id=session.user_id,
                amr=session.amr,
                created_at=session.created_at,
                ip=session.ip,
                user_agent=session.user_agent,
                revoked_at=session.revoked_at,
            )
        )

    async def get_by_id(self, session_id: UUID) -> AuthSession | None:
        result = await self._session.execute(
            select(*_SESSION_COLUMNS).where(sessions.c.id == session_id)
        )
        row = result.mappings().one_or_none()
        return None if row is None else AuthSession(**row)


class SqlRefreshTokenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, token: RefreshToken) -> None:
        await self._session.execute(
            insert(refresh_tokens).values(
                id=token.id,
                session_id=token.session_id,
                family_id=token.family_id,
                token_hash=token.token_hash,
                expires_at=token.expires_at,
                used_at=token.used_at,
                revoked_at=token.revoked_at,
            )
        )

    async def get_by_hash(self, token_hash: str) -> RefreshToken | None:
        result = await self._session.execute(
            select(*_REFRESH_COLUMNS).where(refresh_tokens.c.token_hash == token_hash)
        )
        row = result.mappings().one_or_none()
        return None if row is None else RefreshToken(**row)


class SqlLoginStateRepository:
    """Contadores de falha, bloqueio e 2FA em `users` (002, design § Modelo de dados)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def estado(self, user_id: UUID) -> EstadoDeLogin | None:
        resultado = await self._session.execute(
            select(
                users.c.id.label("user_id"),
                users.c.failed_logins,
                users.c.locked_until,
                users.c.mfa_enabled,
                users.c.mfa_secret_enc,
                users.c.mfa_last_step,
                users.c.mfa_challenge_jti,
                users.c.mfa_failed_attempts,
            ).where(users.c.id == user_id)
        )
        linha = resultado.mappings().one_or_none()
        return None if linha is None else EstadoDeLogin(**linha)

    async def registrar_falha(self, user_id: UUID, agora: datetime) -> EstadoDeLogin:
        falhas = users.c.failed_logins + 1
        await self._session.execute(
            update(users)
            .where(users.c.id == user_id)
            .values(
                failed_logins=case((falhas >= FALHAS_PARA_BLOQUEIO, 0), else_=falhas),
                locked_until=case(
                    (falhas >= FALHAS_PARA_BLOQUEIO, agora + DURACAO_DO_BLOQUEIO),
                    else_=users.c.locked_until,
                ),
            )
        )
        estado = await self.estado(user_id)
        if estado is None:  # pragma: no cover - o usuário acabou de ser lido pelo login
            raise LookupError("usuário sumiu durante o login")
        return estado

    async def registrar_sucesso(self, user_id: UUID, agora: datetime) -> None:
        await self._session.execute(
            update(users)
            .where(users.c.id == user_id)
            .values(failed_logins=0, locked_until=None, last_login_at=agora)
        )

    async def novo_desafio(self, user_id: UUID, jti: UUID) -> None:
        await self._session.execute(
            update(users)
            .where(users.c.id == user_id)
            .values(mfa_challenge_jti=jti, mfa_failed_attempts=0)
        )

    async def falha_de_mfa(self, user_id: UUID) -> int:
        tentativas = users.c.mfa_failed_attempts + 1
        resultado = await self._session.execute(
            update(users)
            .where(users.c.id == user_id)
            .values(
                mfa_failed_attempts=tentativas,
                mfa_challenge_jti=case(
                    (tentativas >= TENTATIVAS_DE_MFA, None), else_=users.c.mfa_challenge_jti
                ),
            )
            .returning(users.c.mfa_failed_attempts)
        )
        return int(resultado.scalar_one())

    async def gravar_segredo(self, user_id: UUID, segredo_cifrado: str) -> None:
        await self._session.execute(
            update(users).where(users.c.id == user_id).values(mfa_secret_enc=segredo_cifrado)
        )

    async def concluir_mfa(self, user_id: UUID, passo: int, *, ativar: bool) -> None:
        valores: dict[str, object] = {
            "mfa_last_step": passo,
            "mfa_challenge_jti": None,
            "mfa_failed_attempts": 0,
        }
        if ativar:
            valores["mfa_enabled"] = True
        await self._session.execute(update(users).where(users.c.id == user_id).values(**valores))


class SqlSessionRevoker:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def revogar(self, session_id: UUID, agora: datetime) -> None:
        await self._session.execute(
            update(sessions)
            .where(sessions.c.id == session_id, sessions.c.revoked_at.is_(None))
            .values(revoked_at=agora)
        )
        await self._session.execute(
            update(refresh_tokens)
            .where(refresh_tokens.c.session_id == session_id, refresh_tokens.c.revoked_at.is_(None))
            .values(revoked_at=agora)
        )


class SqlRefreshTokenWriter:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def marcar_usado(self, token_id: UUID, agora: datetime) -> bool:
        resultado = await self._session.execute(
            update(refresh_tokens)
            .where(refresh_tokens.c.id == token_id, refresh_tokens.c.used_at.is_(None))
            .values(used_at=agora)
            .returning(refresh_tokens.c.id)
        )
        return resultado.scalar_one_or_none() is not None
