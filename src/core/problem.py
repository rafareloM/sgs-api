"""Respostas de erro em application/problem+json, RFC 9457 (spec 001, R3).

Nenhuma resposta ecoa o valor recebido, stack trace, SQL ou caminho interno.
"""

from collections.abc import Mapping, Sequence
from http import HTTPStatus
from typing import Any, cast

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.core.errors import AppError, DomainValidationError, FieldError

PROBLEM_JSON = "application/problem+json"

_VALIDATION_TYPE = DomainValidationError.type
_VALIDATION_TITLE = DomainValidationError.title


def problem_response(
    *,
    status: int,
    type_: str,
    title: str,
    detail: str,
    request_id: str | None,
    headers: Mapping[str, str] | None = None,
    errors: Sequence[FieldError] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": type_,
        "title": title,
        "status": status,
        "detail": detail,
        "request_id": request_id,
    }
    if errors is not None:
        body["errors"] = [{"campo": e.campo, "mensagem": e.mensagem} for e in errors]
    return JSONResponse(body, status_code=status, media_type=PROBLEM_JSON, headers=headers)


def internal_error_response(request_id: str) -> JSONResponse:
    """Resposta 500 genérica (R3.3); os detalhes ficam só no log, ligados pelo request_id."""
    return problem_response(
        status=500,
        type_="urn:sgs:problema:erro-interno",
        title="Erro interno",
        detail="Ocorreu um erro inesperado. Informe o request_id ao suporte.",
        request_id=request_id,
    )


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _handle_app_error)
    app.add_exception_handler(RequestValidationError, _handle_request_validation)
    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)


def _request_id(request: Request) -> str | None:
    request_id = getattr(request.state, "request_id", None)
    return request_id if isinstance(request_id, str) else None


async def _handle_app_error(request: Request, exc: Exception) -> JSONResponse:
    error = cast(AppError, exc)
    errors = error.errors if isinstance(error, DomainValidationError) else None
    return problem_response(
        status=error.status,
        type_=error.type,
        title=error.title,
        detail=error.detail,
        request_id=_request_id(request),
        errors=errors,
    )


async def _handle_request_validation(request: Request, exc: Exception) -> JSONResponse:
    error = cast(RequestValidationError, exc)
    return problem_response(
        status=422,
        type_=_VALIDATION_TYPE,
        title=_VALIDATION_TITLE,
        detail="A requisição tem campos inválidos.",
        request_id=_request_id(request),
        errors=[_field_error(item) for item in error.errors()],
    )


# Título e detalhe em português para erros HTTP gerados pelo framework (rota inexistente etc.).
_HTTP_PROBLEMS: dict[int, tuple[str, str, str]] = {
    400: ("requisicao-invalida", "Requisição inválida", "A requisição não pôde ser entendida."),
    401: ("nao-autenticado", "Não autenticado", "É preciso se autenticar."),
    403: ("acesso-negado", "Acesso negado", "Você não tem permissão para esta ação."),
    404: ("nao-encontrado", "Recurso não encontrado", "O recurso pedido não existe."),
    405: ("metodo-nao-permitido", "Método não permitido", "O método não é aceito nesta rota."),
    413: ("corpo-muito-grande", "Corpo muito grande", "O corpo da requisição é grande demais."),
    415: ("midia-nao-suportada", "Tipo de mídia não suportado", "Envie o corpo como JSON."),
    429: ("muitas-requisicoes", "Muitas requisições", "Aguarde um pouco e tente de novo."),
}


async def _handle_http_exception(request: Request, exc: Exception) -> JSONResponse:
    error = cast(StarletteHTTPException, exc)
    status = error.status_code
    if status in _HTTP_PROBLEMS:
        slug, title, detail = _HTTP_PROBLEMS[status]
        type_ = f"urn:sgs:problema:{slug}"
    else:
        type_, title, detail = "about:blank", HTTPStatus(status).phrase, HTTPStatus(status).phrase
    # Um detalhe próprio (em português) prevalece sobre o texto padrão do framework.
    if isinstance(error.detail, str) and error.detail != HTTPStatus(status).phrase:
        detail = error.detail
    return problem_response(
        status=status,
        type_=type_,
        title=title,
        detail=detail,
        request_id=_request_id(request),
        headers=error.headers,
    )


_SOURCES = {"body": "corpo", "query": "consulta", "path": "caminho", "header": "cabeçalho"}

_MESSAGES = {
    "missing": "Campo obrigatório.",
    "extra_forbidden": "Campo não permitido.",
    "json_invalid": "JSON inválido.",
    "string_type": "Deve ser um texto.",
    "string_too_short": "Deve ter pelo menos {min_length} caractere(s).",
    "string_too_long": "Deve ter no máximo {max_length} caractere(s).",
    "string_pattern_mismatch": "Formato inválido.",
    "int_type": "Deve ser um número inteiro.",
    "int_parsing": "Deve ser um número inteiro.",
    "int_from_float": "Deve ser um número inteiro.",
    "float_type": "Deve ser um número.",
    "float_parsing": "Deve ser um número.",
    "decimal_parsing": "Deve ser um número.",
    "bool_type": "Deve ser verdadeiro ou falso.",
    "bool_parsing": "Deve ser verdadeiro ou falso.",
    "greater_than": "Deve ser maior que {gt}.",
    "greater_than_equal": "Deve ser maior ou igual a {ge}.",
    "less_than": "Deve ser menor que {lt}.",
    "less_than_equal": "Deve ser menor ou igual a {le}.",
    "multiple_of": "Deve ser múltiplo de {multiple_of}.",
    "enum": "Valor inválido. Use um destes: {expected}.",
    "literal_error": "Valor inválido. Use um destes: {expected}.",
    "too_short": "Deve ter pelo menos {min_length} item(ns).",
    "too_long": "Deve ter no máximo {max_length} item(ns).",
    "list_type": "Deve ser uma lista.",
    "dict_type": "Deve ser um objeto.",
    "model_type": "Deve ser um objeto.",
    "model_attributes_type": "Deve ser um objeto.",
    "uuid_type": "Deve ser um UUID válido.",
    "uuid_parsing": "Deve ser um UUID válido.",
    "date_type": "Deve ser uma data válida (AAAA-MM-DD).",
    "date_parsing": "Deve ser uma data válida (AAAA-MM-DD).",
    "date_from_datetime_parsing": "Deve ser uma data válida (AAAA-MM-DD).",
    "datetime_type": "Deve ser data e hora válidas (ISO 8601).",
    "datetime_parsing": "Deve ser data e hora válidas (ISO 8601).",
    "datetime_from_date_parsing": "Deve ser data e hora válidas (ISO 8601).",
    "timezone_aware": "Informe o fuso horário.",
    "url_type": "Deve ser uma URL válida.",
    "url_parsing": "Deve ser uma URL válida.",
}
_FALLBACK_MESSAGE = "Valor inválido."


def _field_error(item: Mapping[str, Any]) -> FieldError:
    kind = str(item.get("type", ""))
    return FieldError(campo=_field_name(item.get("loc", ()), kind), mensagem=_message(kind, item))


def _field_name(loc: Sequence[str | int], kind: str) -> str:
    parts = list(loc)
    source = str(parts.pop(0)) if parts and parts[0] in _SOURCES else None
    if kind == "json_invalid" or not parts:
        return _SOURCES.get(source or "body", "corpo")
    name = ""
    for part in parts:
        if isinstance(part, int):
            name += f"[{part}]"
        else:
            name += f".{part}" if name else part
    return name


def _message(kind: str, item: Mapping[str, Any]) -> str:
    context = dict(item.get("ctx") or {})
    if kind in {"value_error", "assertion_error"} and "error" in context:
        # Validadores do projeto escrevem a mensagem em português.
        return str(context["error"])
    template = _MESSAGES.get(kind)
    if template is None:
        return _FALLBACK_MESSAGE
    if "expected" in context:
        context["expected"] = str(context["expected"]).replace(" or ", " ou ")
    try:
        return template.format_map(context)
    except (KeyError, IndexError, ValueError):
        return _FALLBACK_MESSAGE
