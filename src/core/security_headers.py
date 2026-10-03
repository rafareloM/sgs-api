"""Cabeçalhos de segurança em todas as respostas (spec 001, R6.1).

O R6.1 pede os cabeçalhos nas rotas autenticadas; aplicá-los a todas é o mais restritivo e
dispensa saber, aqui, quais rotas exigem login. Uma rota pode definir o próprio Cache-Control
(por exemplo, um JWKS público com cache curto); os demais cabeçalhos são sempre sobrescritos.
"""

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_ALWAYS = {
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}
_DEFAULT_CACHE_CONTROL = "no-store"


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in _ALWAYS.items():
                    headers[name] = value
                headers.setdefault("Cache-Control", _DEFAULT_CACHE_CONTROL)
            await send(message)

        await self.app(scope, receive, send_with_headers)
