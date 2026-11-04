"""Entidade Perfil (Etapa 02 - Banco de Dados)."""

from dataclasses import dataclass

from src.core.errors import DomainValidationError, FieldError


@dataclass(frozen=True)
class Perfil:
    nome_perfil: str
    permissoes: str
    id_perfil: int | None = None

    def __post_init__(self) -> None:
        errors: list[FieldError] = []
        if not self.nome_perfil or not self.nome_perfil.strip():
            errors.append(
                FieldError(campo="nome_perfil", mensagem="Nome do perfil não pode ser vazio.")
            )
        if not self.permissoes or not self.permissoes.strip():
            errors.append(
                FieldError(campo="permissoes", mensagem="Permissões não podem ser vazias.")
            )
        if errors:
            raise DomainValidationError("Dados de perfil inválidos.", errors=errors)
