"""Erros da aplicação (spec 001, R3).

Só stdlib: o domain de todos os módulos importa este arquivo. A conversão para HTTP fica em
`core/problem.py`.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import ClassVar


@dataclass(frozen=True)
class FieldError:
    """Problema em um campo de entrada, como aparece em `errors[]` da resposta 422."""

    campo: str
    mensagem: str


class AppError(Exception):
    """Erro de negócio. A API responde com o status, o tipo e o título da subclasse."""

    status: ClassVar[int] = 400
    type: ClassVar[str] = "urn:sgs:problema:requisicao-invalida"
    title: ClassVar[str] = "Requisição inválida"

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class NotFound(AppError):
    status = 404
    type = "urn:sgs:problema:nao-encontrado"
    title = "Recurso não encontrado"


class Forbidden(AppError):
    status = 403
    type = "urn:sgs:problema:acesso-negado"
    title = "Acesso negado"


class Conflict(AppError):
    status = 409
    type = "urn:sgs:problema:conflito"
    title = "Conflito"


class DomainValidationError(AppError):
    status = 422
    type = "urn:sgs:problema:validacao"
    title = "Dados inválidos"

    def __init__(self, detail: str, errors: Sequence[FieldError] = ()) -> None:
        super().__init__(detail)
        self.errors = tuple(errors)
