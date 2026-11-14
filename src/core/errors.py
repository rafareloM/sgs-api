"""Erros da aplicação (spec 001, R3).

Só stdlib: o domain de todos os módulos importa este arquivo. A conversão para HTTP fica em
`core/problem.py`.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import ClassVar


@dataclass(frozen=True)
class FieldError:
    """Problema em um campo de entrada, como aparece em `errors[]` da resposta 422."""

    campo: str
    mensagem: str


class AppError(Exception):
    """Erro de negócio. A API responde com o status, o tipo e o título da subclasse.

    `extensoes` são membros a mais no corpo da resposta (RFC 9457, § 3.2), como o id da unidade
    que já existe num 409; nunca substituem os membros padrão.
    """

    status: ClassVar[int] = 400
    type: ClassVar[str] = "urn:sgs:problema:requisicao-invalida"
    title: ClassVar[str] = "Requisição inválida"

    def __init__(self, detail: str, *, extensoes: Mapping[str, object] | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        self.extensoes: Mapping[str, object] = MappingProxyType(dict(extensoes or {}))


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


class PreconditionFailed(AppError):
    """412: a versão do `If-Match` não é mais a atual do recurso (006/R3.2)."""

    status = 412
    type = "urn:sgs:problema:versao-desatualizada"
    title = "Versão desatualizada"


class PreconditionRequired(AppError):
    """428: a alteração exige `If-Match` com a versão em mãos (006/R3.2; RFC 6585, § 3)."""

    status = 428
    type = "urn:sgs:problema:versao-exigida"
    title = "Versão exigida"


class DomainValidationError(AppError):
    status = 422
    type = "urn:sgs:problema:validacao"
    title = "Dados inválidos"

    def __init__(self, detail: str, errors: Sequence[FieldError] = ()) -> None:
        super().__init__(detail)
        self.errors = tuple(errors)
