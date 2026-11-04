"""Entidade Alteracao (Etapa 02 - Banco de Dados)."""

from dataclasses import dataclass
from datetime import datetime

from src.core.errors import DomainValidationError, FieldError


@dataclass(frozen=True)
class Alteracao:
    campo_alterado: str
    id_unidade: int
    id_usuario: int
    valor_anterior: str | None = None
    valor_novo: str | None = None
    data_hora: datetime | None = None
    id_alteracao: int | None = None

    def __post_init__(self) -> None:
        errors: list[FieldError] = []

        if not self.campo_alterado or not self.campo_alterado.strip():
            errors.append(
                FieldError(campo="campo_alterado", mensagem="Campo alterado não pode ser vazio.")
            )

        if self.valor_anterior is None and self.valor_novo is None:
            errors.append(
                FieldError(
                    campo="valores",
                    mensagem="Pelo menos um dos valores (anterior ou novo) deve ser informado.",
                )
            )

        if errors:
            raise DomainValidationError("Dados de alteração inválidos.", errors=errors)
