"""Login OIDC: a identidade aceita do provedor e a porta do adaptador (spec 004, design
§ Portas e adaptadores e § Fluxo, Login OIDC).

O adaptador (Authlib e PyJWT) fica em `infrastructure/authlib_oidc.py`. Ele monta a URL de
autorização, troca o código e confere o `id_token` antes de devolver um `OidcIdentity`.
"""

import base64
import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

NONCE_MAX = 64


@dataclass(frozen=True)
class OidcLoginRequest:
    """Início de um login OIDC guardado no banco (D004-2). `state` e vínculo só em SHA-256; o
    `code_verifier` cifrado com `FieldCipher`, AAD = `id`."""

    id: UUID
    state_hash: str
    binding_hash: str
    nonce: str
    code_verifier_enc: str
    created_at: datetime
    expires_at: datetime


# Motivos de recusa da troca (design § Fluxo, Login OIDC, passo 3). Vão para a auditoria
# (`auth.oidc_failed`): lista fechada, sem o código, o token, o segredo nem o e-mail.
MotivoDeRecusa = Literal["troca", "assinatura", "iss", "aud", "exp", "nonce", "acr", "claims"]


@dataclass(frozen=True)
class OidcIdentity:
    """Quem o provedor diz que é, tirado de um `id_token` já conferido."""

    sub: str
    username: str  # preferred_username, em minúsculas
    email: str | None  # só com email_verified = true (D004-12)
    display_name: str
    groups: tuple[str, ...]  # claim OIDC_GROUPS_CLAIM
    acr: str | None


class OidcRejected(Exception):  # noqa: N818 - nome do design da 004
    """A troca do código ou a conferência do `id_token` falhou. Leva só o motivo."""

    def __init__(self, motivo: MotivoDeRecusa) -> None:
        super().__init__(motivo)
        self.motivo: MotivoDeRecusa = motivo


class OidcPort(Protocol):
    async def authorization_url(self, *, state: str, nonce: str, code_challenge: str) -> str:
        """URL do provedor para o login: Authorization Code com PKCE S256, `state`, `nonce` e o
        `redirect_uri` da configuração (R3.1, R3.8); com OIDC_REQUIRED_ACR, `acr_values` (R3.6).
        Levanta `ServiceUnavailable` se o provedor não puder ser usado (fora do ar, ou descoberta
        de outro emissor)."""
        ...

    async def exchange(self, code: str, *, code_verifier: str, nonce: str) -> OidcIdentity:
        """Troca o código e confere o `id_token`: assinatura, `iss`, `aud`, `exp`, `nonce` (R3.2)
        e, com OIDC_REQUIRED_ACR, o `acr` (R3.6). Levanta `OidcRejected` com o motivo."""
        ...


def hash_do_valor(valor: str) -> str:
    """SHA-256 em hex do `state` ou do vínculo: só o hash fica no banco (D004-2)."""
    return hashlib.sha256(valor.encode()).hexdigest()


def mesmo_valor(a: str, b: str) -> bool:
    """Comparação em tempo constante dos hashes."""
    return hmac.compare_digest(a, b)


def code_challenge_s256(code_verifier: str) -> str:
    """PKCE S256 (RFC 7636 § 4.2): base64url, sem `=`, do SHA-256 do `code_verifier`."""
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
