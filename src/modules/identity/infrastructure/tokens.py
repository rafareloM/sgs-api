"""`TokenService` com PyJWT e ES256 (spec 002, R3.1, R3.2 e R3.8; design, § Chaves JWT).

O relógio injetado vale para a emissão (`iat` e `exp`); a validação usa o relógio do sistema,
porque o PyJWT confere `exp` contra a hora atual.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Self
from uuid import UUID

import jwt
from cryptography.hazmat.primitives.asymmetric import ec
from jwt.algorithms import ECAlgorithm

from src.core.config import Settings
from src.core.ids import uuid7
from src.modules.identity.domain.sessions import AuthSession
from src.modules.identity.domain.tokens import (
    ACCESS_TOKEN_TTL,
    MFA_TOKEN_TTL,
    AccessTokenClaims,
    InvalidTokenError,
    IssuedAccessToken,
    IssuedMfaToken,
    MfaPurpose,
    MfaTokenClaims,
    PublicJwk,
)

ALGORITHM = "ES256"
ISSUER = "sgs-api"
ACCESS_AUDIENCE = "sgs-api"
MFA_AUDIENCE = "sgs-mfa"  # design, § Chaves JWT


@dataclass(frozen=True)
class SigningKey:
    kid: str
    private_key: ec.EllipticCurvePrivateKey = field(repr=False)


def _now() -> datetime:
    return datetime.now(UTC)


class JwtTokenService:
    """Assina com a primeira chave (a ativa) e valida com qualquer uma delas."""

    def __init__(self, keys: Sequence[SigningKey], *, clock: Callable[[], datetime] = _now) -> None:
        if not keys:
            raise ValueError("informe ao menos uma chave de assinatura")
        self._public_keys = {key.kid: key.private_key.public_key() for key in keys}
        if len(self._public_keys) != len(keys):
            raise ValueError("cada chave de assinatura precisa de um kid próprio")
        self._active = keys[0]
        self._clock = clock

    @classmethod
    def from_settings(cls, settings: Settings) -> Self:
        """Chaves de JWT_PRIVATE_KEYS (ou do arquivo), já validadas pelo `Settings`."""
        return cls([SigningKey(key.kid, key.private_key()) for key in settings.jwt_signing_keys])

    def issue_access_token(self, session: AuthSession) -> IssuedAccessToken:
        now = self._clock()
        claims = {
            "iss": ISSUER,
            "aud": ACCESS_AUDIENCE,
            "sub": str(session.user_id),
            "sid": str(session.id),
            "amr": session.amr.split("+"),
            "iat": now,
            "exp": now + ACCESS_TOKEN_TTL,
        }
        return IssuedAccessToken(
            token=self._sign(claims), expires_in=int(ACCESS_TOKEN_TTL.total_seconds())
        )

    def verify_access_token(self, token: str) -> AccessTokenClaims:
        claims = self._verify(token, ACCESS_AUDIENCE, ("sub", "sid", "amr"))
        try:
            amr = claims["amr"]
            if not isinstance(amr, list) or not all(isinstance(item, str) for item in amr):
                raise InvalidTokenError
            return AccessTokenClaims(
                user_id=UUID(claims["sub"]), session_id=UUID(claims["sid"]), amr=tuple(amr)
            )
        except (TypeError, ValueError):
            raise InvalidTokenError from None

    def issue_mfa_token(self, user_id: UUID, purpose: MfaPurpose) -> IssuedMfaToken:
        now = self._clock()
        jti = uuid7()
        claims = {
            "iss": ISSUER,
            "aud": MFA_AUDIENCE,
            "sub": str(user_id),
            "purpose": purpose.value,
            "jti": str(jti),
            "iat": now,
            "exp": now + MFA_TOKEN_TTL,
        }
        return IssuedMfaToken(token=self._sign(claims), jti=jti, purpose=purpose)

    def verify_mfa_token(self, token: str, purpose: MfaPurpose) -> MfaTokenClaims:
        claims = self._verify(token, MFA_AUDIENCE, ("sub", "purpose", "jti"))
        if claims["purpose"] != purpose.value:
            raise InvalidTokenError
        try:
            return MfaTokenClaims(
                user_id=UUID(claims["sub"]), jti=UUID(claims["jti"]), purpose=purpose
            )
        except (TypeError, ValueError):
            raise InvalidTokenError from None

    def public_keys(self) -> tuple[PublicJwk, ...]:
        jwks = []
        for kid, public_key in self._public_keys.items():
            jwk = ECAlgorithm.to_jwk(public_key, as_dict=True)
            jwks.append(PublicJwk(kid=kid, x=jwk["x"], y=jwk["y"]))
        return tuple(jwks)

    def _sign(self, claims: dict[str, Any]) -> str:
        return jwt.encode(
            claims, self._active.private_key, algorithm=ALGORITHM, headers={"kid": self._active.kid}
        )

    def _verify(self, token: str, audience: str, claims: Sequence[str]) -> dict[str, Any]:
        """Confere `kid`, assinatura ES256, `iss`, `aud` e validade; qualquer falha vira 401."""
        try:
            kid = jwt.get_unverified_header(token).get("kid")
            public_key = self._public_keys.get(kid) if isinstance(kid, str) else None
            if public_key is None:
                raise InvalidTokenError
            decoded: dict[str, Any] = jwt.decode(
                token,
                public_key,
                algorithms=[ALGORITHM],  # só ES256: nem `none`, nem HMAC com a chave pública
                audience=audience,
                issuer=ISSUER,
                options={"require": ["iss", "aud", "iat", "exp", *claims]},
            )
        except jwt.PyJWTError:
            # `from None`: a exceção do PyJWT pode trazer trechos do token.
            raise InvalidTokenError from None
        return decoded
