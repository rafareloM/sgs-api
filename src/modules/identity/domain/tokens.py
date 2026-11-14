"""Tokens da API (spec 002, R3.1, R3.2 e R3.8; design, § Chaves JWT).

`TokenService` é a porta que emite e valida os JWT: o access token da sessão e o `mfa_token` do
segundo fator. A implementação (PyJWT, ES256) fica em `infrastructure/tokens.py` e é montada pela
raiz de composição (`src/main.py`, em `app.state.token_service`).

Quem valida o Bearer (o `CurrentUser`, 003/T4) chama `verify_access_token`, que confere
assinatura, `kid`, `iss`, `aud` e validade, e recebe `user_id` (`sub`) e `session_id` (`sid`).
A revogação da sessão não está no token: o `CurrentUser` ainda carrega a sessão `sid` e o usuário
e recusa sessão revogada ou usuário inativo (o resto da R3.8).
"""

from dataclasses import dataclass, field
from datetime import timedelta
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from src.core.errors import AppError
from src.modules.identity.domain.sessions import AuthSession

ACCESS_TOKEN_TTL = timedelta(minutes=15)  # R3.1
MFA_TOKEN_TTL = timedelta(minutes=5)  # R1.1


class MfaPurpose(StrEnum):
    """Para que serve o `mfa_token` (claim `purpose`)."""

    ENROLL = "enroll"  # R1.2: só cadastra o 2FA
    VERIFY = "verify"  # R1.1: confere o código TOTP


class InvalidTokenError(AppError):
    """Token ausente do formato, com assinatura ou `kid` inválidos, de outro emissor ou público,
    de outra finalidade ou vencido. A mensagem é sempre a mesma, para não dizer o que falhou."""

    status = 401
    type = "urn:sgs:problema:nao-autenticado"
    title = "Não autenticado"

    def __init__(self) -> None:
        super().__init__("Token inválido ou expirado.")


@dataclass(frozen=True)
class IssuedAccessToken:
    """Access token emitido, para a resposta `{access_token, expires_in}`."""

    token: str = field(repr=False)
    expires_in: int  # segundos


@dataclass(frozen=True)
class AccessTokenClaims:
    """O que um access token válido diz: quem é (`sub`), de qual sessão (`sid`) e como entrou."""

    user_id: UUID
    session_id: UUID
    amr: tuple[str, ...]


@dataclass(frozen=True)
class IssuedMfaToken:
    """`mfa_token` emitido. O `jti` vai para `users.mfa_challenge_jti` (R2.6)."""

    token: str = field(repr=False)
    jti: UUID
    purpose: MfaPurpose


@dataclass(frozen=True)
class MfaTokenClaims:
    user_id: UUID
    jti: UUID
    purpose: MfaPurpose


@dataclass(frozen=True)
class PublicJwk:
    """Chave pública de verificação no formato JWK (RFC 7517 e 7518), publicada no JWKS (R3.2)."""

    kid: str
    x: str
    y: str
    kty: str = "EC"
    crv: str = "P-256"
    alg: str = "ES256"
    use: str = "sig"


class TokenService(Protocol):
    def issue_access_token(self, session: AuthSession) -> IssuedAccessToken:
        """JWT ES256 de 15 minutos com `sub`, `sid`, `iss`, `aud`, `iat`, `exp`, `amr` e o
        `kid` da chave ativa no cabeçalho (R3.1)."""
        ...

    def verify_access_token(self, token: str) -> AccessTokenClaims:
        """Levanta `InvalidTokenError` se o token não for um access token válido desta API."""
        ...

    def issue_mfa_token(self, user_id: UUID, purpose: MfaPurpose) -> IssuedMfaToken:
        """JWT de 5 minutos, `aud = sgs-mfa`, com `purpose` e um `jti` novo (design)."""
        ...

    def verify_mfa_token(self, token: str, purpose: MfaPurpose) -> MfaTokenClaims:
        """Levanta `InvalidTokenError` se o token não for um `mfa_token` válido para `purpose`."""
        ...

    def public_keys(self) -> tuple[PublicJwk, ...]:
        """Chaves públicas de todas as chaves configuradas, a ativa e as antigas (R3.2)."""
        ...
