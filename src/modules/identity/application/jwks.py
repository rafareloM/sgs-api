"""Publicação das chaves públicas de verificação no JWKS (spec 002, R3.2)."""

from src.modules.identity.domain.tokens import PublicJwk, TokenService

# Reexportados para a camada api, que só importa a application (design da 002, Decisões).
__all__ = ["PublicJwk", "TokenService", "chaves_publicas"]


def chaves_publicas(tokens: TokenService) -> tuple[PublicJwk, ...]:
    """Chaves públicas da chave ativa e das antigas: um token assinado antes de uma rotação
    continua verificável até vencer."""
    return tokens.public_keys()
