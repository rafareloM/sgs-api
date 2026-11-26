"""Usuário (spec 002; docs/architecture/modelo-dados.md § 1).

R1.7: a senha só é guardada como hash Argon2id, no formato PHC que o `PasswordHasher` (T3)
produz. Usuário de diretório (LDAP, OIDC) não tem senha local e é identificado pelo
`external_id` (DN ou `sub`).
"""

import re
from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID

from src.core.errors import DomainValidationError, FieldError

USERNAME_MAX = 100
DISPLAY_NAME_MAX = 200
EMAIL_MAX = 254
EXTERNAL_ID_MAX = 512

# $argon2id$v=19$m=<memória KiB>,t=<iterações>,p=<paralelismo>$<sal base64>$<hash base64>
ARGON2ID_PHC = re.compile(
    r"\$argon2id\$v=19\$m=[0-9]+,t=[0-9]+,p=[0-9]+\$[A-Za-z0-9+/]+\$[A-Za-z0-9+/]+"
)
_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")


class UserSource(StrEnum):
    LOCAL = "local"
    LDAP = "ldap"
    OIDC = "oidc"


def normalize_username(username: str) -> str:
    """Nomes de usuário são guardados e buscados em minúsculas, sem espaços nas pontas."""
    return username.strip().lower()


def is_valid_email(email: str) -> bool:
    """Se `User` aceita o e-mail, já em minúsculas e sem espaços nas pontas, como ele o guarda."""
    return len(email) <= EMAIL_MAX and _EMAIL.fullmatch(email) is not None


@dataclass(frozen=True)
class User:
    id: UUID
    username: str
    display_name: str
    source: UserSource
    # Fora do repr: um usuário que vá parar num log não leva o hash junto.
    password_hash: str | None = field(default=None, repr=False)
    email: str | None = None
    external_id: str | None = None
    is_active: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "username", normalize_username(self.username))
        object.__setattr__(self, "display_name", self.display_name.strip())
        object.__setattr__(self, "source", UserSource(self.source))
        if self.email is not None:
            # Minúsculas para a unicidade não depender de como o e-mail foi digitado.
            object.__setattr__(self, "email", self.email.strip().lower())

        errors = [
            *_check_name("username", self.username, USERNAME_MAX, "Informe o nome de usuário."),
            *_check_name(
                "display_name", self.display_name, DISPLAY_NAME_MAX, "Informe o nome de exibição."
            ),
            *self._check_email(),
            *self._check_credentials(),
        ]
        if errors:
            raise DomainValidationError("Dados de usuário inválidos.", errors=errors)

    def _check_email(self) -> list[FieldError]:
        if self.email is None or is_valid_email(self.email):
            return []
        return [FieldError(campo="email", mensagem="E-mail inválido.")]

    def _check_credentials(self) -> list[FieldError]:
        errors: list[FieldError] = []
        if self.source is UserSource.LOCAL:
            if self.password_hash is None or not ARGON2ID_PHC.fullmatch(self.password_hash):
                errors.append(
                    FieldError(
                        campo="password_hash",
                        mensagem="A senha só pode ser guardada como hash Argon2id.",
                    )
                )
            if self.external_id is not None:
                errors.append(
                    FieldError(
                        campo="external_id",
                        mensagem="Usuário local não tem identificador externo.",
                    )
                )
            return errors

        if self.password_hash is not None:
            errors.append(
                FieldError(
                    campo="password_hash", mensagem="Usuário de diretório não tem senha local."
                )
            )
        if not self.external_id or len(self.external_id) > EXTERNAL_ID_MAX:
            errors.append(
                FieldError(
                    campo="external_id",
                    mensagem="Informe o identificador no diretório (DN ou sub).",
                )
            )
        return errors


def _check_name(campo: str, valor: str, maximo: int, vazio: str) -> list[FieldError]:
    if not valor:
        return [FieldError(campo=campo, mensagem=vazio)]
    if len(valor) > maximo:
        return [FieldError(campo=campo, mensagem=f"Use até {maximo} caracteres.")]
    return []
