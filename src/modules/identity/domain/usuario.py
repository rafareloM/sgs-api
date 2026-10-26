"""Entidade Usuario (Etapa 02 - Banco de Dados)."""

import re
from dataclasses import dataclass

from src.core.errors import DomainValidationError, FieldError

EMAIL_REGEX = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")


@dataclass(frozen=True)
class Usuario:
    nome: str
    email: str
    senha_hash: str
    id_perfil: int
    dois_fator_habilitado: bool = False
    dois_fator_segredo: str | None = None
    id_unidade: int | None = None
    id_usuario: int | None = None

    def __post_init__(self) -> None:
        errors: list[FieldError] = []
        if not self.nome or not self.nome.strip():
            errors.append(FieldError(campo="nome", mensagem="Nome não pode ser vazio."))

        if not self.email or not EMAIL_REGEX.fullmatch(self.email):
            errors.append(FieldError(campo="email", mensagem="Formato de e-mail inválido."))

        if not self.senha_hash or len(self.senha_hash) < 60:
            errors.append(
                FieldError(
                    campo="senha_hash",
                    mensagem="Hash de senha deve ter no mínimo 60 caracteres.",
                )
            )

        if self.dois_fator_habilitado and (
            not self.dois_fator_segredo or not self.dois_fator_segredo.strip()
        ):
            errors.append(
                FieldError(
                    campo="dois_fator_segredo",
                    mensagem="Segredo do segundo fator é obrigatório quando 2FA habilitado.",
                )
            )

        if errors:
            raise DomainValidationError("Dados de usuário inválidos.", errors=errors)
