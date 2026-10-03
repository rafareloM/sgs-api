"""Logs estruturados em JSON, com filtro de dados sensíveis (spec 001, R4.1 e R4.3)."""

import logging
import re
import sys
from collections.abc import Mapping
from typing import Any

import structlog
from structlog.typing import EventDict, Processor, WrappedLogger

REDACTED = "***"

# Chaves cujo valor nunca vai para o log, em qualquer nível de aninhamento do evento.
_SENSITIVE_KEY = re.compile(
    r"senha|password|passwd|secret|segredo|token|cookie|authorization|credential|credencial"
    r"|api[_-]?key|private[_-]?key|chave[_-]?privada|otp",
    re.IGNORECASE,
)
_SENSITIVE_EXACT_KEYS = frozenset({"code", "codigo"})  # código TOTP enviado no 2FA

# Segredos que podem aparecer dentro de textos livres, como mensagens e tracebacks.
_SECRETS_IN_TEXT = (
    (re.compile(r"(?i)\b(bearer|basic)\s+[^\s,;\"']+"), rf"\1 {REDACTED}"),
    (re.compile(r"\beyJ[\w-]+\.[\w-]+\.[\w-]*"), REDACTED),  # JWT
)


def redact_sensitive(_logger: WrappedLogger, _method: str, event_dict: EventDict) -> EventDict:
    """Processador do structlog: mascara chaves sensíveis e tokens dentro de textos."""
    return {key: _redact_entry(key, value) for key, value in event_dict.items()}


def _redact_entry(key: object, value: Any) -> Any:
    name = str(key)
    if name.lower() in _SENSITIVE_EXACT_KEYS or _SENSITIVE_KEY.search(name):
        return REDACTED
    return _scrub(value)


def _scrub(value: Any) -> Any:
    if isinstance(value, str):
        for pattern, replacement in _SECRETS_IN_TEXT:
            value = pattern.sub(replacement, value)
        return value
    if isinstance(value, Mapping):
        return {key: _redact_entry(key, item) for key, item in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [_scrub(item) for item in value]
    return value


def _drop_color_message(_logger: WrappedLogger, _method: str, event_dict: EventDict) -> EventDict:
    """O uvicorn anexa uma cópia da mensagem com códigos de cor ANSI; no JSON ela só polui."""
    event_dict.pop("color_message", None)
    return event_dict


def configure_logging(level: str = "INFO") -> None:
    """Faz structlog e o logging da stdlib (uvicorn, alembic...) escreverem JSON em stdout."""
    numeric_level = logging.getLevelNamesMapping()[level]
    shared: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]
    rendering: list[Processor] = [
        structlog.processors.format_exc_info,  # traceback em texto, sem variáveis locais
        redact_sensitive,
        structlog.processors.JSONRenderer(),
    ]
    structlog.configure(
        processors=[*shared, *rendering],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        logger_factory=structlog.WriteLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=False,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=[
                *shared,
                structlog.stdlib.add_logger_name,
                structlog.stdlib.ExtraAdder(),
                _drop_color_message,
            ],
            processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, *rendering],
        )
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(numeric_level)
    # O uvicorn instala os próprios handlers; aqui eles passam a usar o handler JSON da raiz.
    for name in ("uvicorn", "uvicorn.error"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers = []
        uvicorn_logger.propagate = True
    # O log de acesso do uvicorn traz a query string; o da API (request_context) a omite.
    # Sem handler e sem propagação, o uvicorn deixa de emiti-lo.
    access_logger = logging.getLogger("uvicorn.access")
    access_logger.handlers = []
    access_logger.propagate = False
    # Clientes HTTP registram a URL completa em INFO, e a query pode levar códigos e tokens.
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(max(numeric_level, logging.WARNING))
