"""Identificador de requisição e log de acesso em JSON (spec 001, R4.1 e R4.2)."""

import re
import time
import uuid

import structlog
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "X-Request-ID"
# O valor recebido vai para logs e respostas; o formato restrito evita injeção nos logs.
_VALID_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,128}")

_access_log = structlog.get_logger("sgs_api.acesso")


class RequestContextMiddleware:
    """Define o request id, devolve-o na resposta e registra uma linha de log por requisição."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _incoming_request_id(scope) or str(uuid.uuid4())
        scope.setdefault("state", {})["request_id"] = request_id
        status_code = 500
        started = time.perf_counter()

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        with structlog.contextvars.bound_contextvars(request_id=request_id):
            try:
                await self.app(scope, receive, send_with_request_id)
            finally:
                # Sem query string nem cabeçalhos: podem carregar tokens (R4.3).
                _access_log.info(
                    "requisicao",
                    method=scope["method"],
                    route=_route_template(scope),
                    status=status_code,
                    duration_ms=round((time.perf_counter() - started) * 1000, 2),
                )


def _incoming_request_id(scope: Scope) -> str | None:
    for name, value in scope["headers"]:
        if name == b"x-request-id":
            candidate: str = value.decode("latin-1")
            return candidate if _VALID_REQUEST_ID.fullmatch(candidate) else None
    return None


def _route_template(scope: Scope) -> str:
    """Rota como declarada (ex.: /unidades/{id}); o caminho cru só quando nenhuma rota casou."""
    path = getattr(scope.get("route"), "path", None)
    return path if isinstance(path, str) else str(scope["path"])
