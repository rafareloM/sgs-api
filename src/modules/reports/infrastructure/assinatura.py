"""`AssinadorDeRelatorio` ES256 com `cryptography` (spec 005, R5.1, R5.4 e R5.5).

Design § Assinatura. Assina o SHA-256 já calculado do arquivo com `ECDSA(Prehashed(SHA256()))`, o
que é exatamente o ES256 sobre o conteúdo inteiro. A assinatura sai em `r‖s` (64 bytes) e
base64url, o formato que a JWK publicada descreve (RFC 7518 § 3.4). Conferência fora da API:
docs/operacao/verificar-relatorio.md.
"""

import base64
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Self

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import Prehashed, decode_dss_signature

from src.core.config import Settings
from src.modules.reports.domain.assinatura import ALGORITMO, Assinatura, PublicJwk

BYTES_DO_SHA256 = 32
BYTES_DA_COORDENADA = 32  # P-256: r, s, x e y têm 256 bits


@dataclass(frozen=True)
class ChaveDeRelatorio:
    kid: str
    private_key: ec.EllipticCurvePrivateKey = field(repr=False)


class Es256AssinadorDeRelatorio:
    """Assina com a primeira chave (a ativa) e publica as públicas de todas (rotação, R5.5)."""

    def __init__(self, chaves: Sequence[ChaveDeRelatorio]) -> None:
        if not chaves:
            raise ValueError("informe ao menos uma chave de assinatura de relatórios")
        if len({chave.kid for chave in chaves}) != len(chaves):
            raise ValueError("cada chave de assinatura de relatórios precisa de um kid próprio")
        self._ativa = chaves[0]
        self._publicas = tuple(_jwk(chave.kid, chave.private_key.public_key()) for chave in chaves)

    @classmethod
    def from_settings(cls, settings: Settings) -> Self | None:
        """Chaves de REPORT_SIGNING_KEYS (ou do arquivo), já validadas pelo `Settings`. Sem chave
        configurada não há assinador, e a exportação fica desligada."""
        chaves = [ChaveDeRelatorio(c.kid, c.private_key()) for c in settings.chaves_de_relatorio]
        return cls(chaves) if chaves else None

    def assinar(self, sha256: bytes) -> Assinatura:
        if len(sha256) != BYTES_DO_SHA256:
            raise ValueError("informe o SHA-256 do arquivo, com 32 bytes")
        der = self._ativa.private_key.sign(sha256, ec.ECDSA(Prehashed(hashes.SHA256())))
        r, s = decode_dss_signature(der)
        r_s = r.to_bytes(BYTES_DA_COORDENADA) + s.to_bytes(BYTES_DA_COORDENADA)
        return Assinatura(kid=self._ativa.kid, algoritmo=ALGORITMO, valor=_base64url(r_s))

    def chaves_publicas(self) -> tuple[PublicJwk, ...]:
        return self._publicas


def _jwk(kid: str, publica: ec.EllipticCurvePublicKey) -> PublicJwk:
    numeros = publica.public_numbers()
    return PublicJwk(
        kid=kid,
        x=_base64url(numeros.x.to_bytes(BYTES_DA_COORDENADA)),
        y=_base64url(numeros.y.to_bytes(BYTES_DA_COORDENADA)),
    )


def _base64url(dados: bytes) -> str:
    """Base64url sem `=` (RFC 7515 § 2), como nas JWK e nas assinaturas JWS."""
    return base64.urlsafe_b64encode(dados).rstrip(b"=").decode("ascii")
