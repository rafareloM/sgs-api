"""Assinatura digital dos relatórios (spec 005, R5; design § Portas e adaptadores, § Assinatura)."""

from dataclasses import dataclass
from typing import Final, Protocol

ALGORITMO: Final = "ES256"


@dataclass(frozen=True)
class Assinatura:
    """Guardada junto com o pedido (R5.1) e devolvida em `integridade` (R5.3)."""

    kid: str
    algoritmo: str
    valor: str  # r‖s (64 bytes) em base64url, sem `=` (RFC 7518 § 3.4)


@dataclass(frozen=True)
class PublicJwk:
    """Chave pública de verificação no formato JWK (RFC 7517 e 7518), publicada para quem
    confere um relatório fora da API (R5.4)."""

    kid: str
    x: str
    y: str
    kty: str = "EC"
    crv: str = "P-256"
    alg: str = ALGORITMO
    use: str = "sig"


class AssinadorDeRelatorio(Protocol):
    def assinar(self, sha256: bytes) -> Assinatura:
        """Assina o SHA-256 do arquivo (32 bytes) com a chave ativa (R5.1)."""
        ...

    def chaves_publicas(self) -> tuple[PublicJwk, ...]:
        """A chave ativa e as anteriores, na ordem configurada (R5.4, R5.5)."""
        ...
