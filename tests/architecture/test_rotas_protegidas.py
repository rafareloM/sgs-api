"""Deny by default: toda rota declara permissão ou está numa lista explícita (spec 003, design
§ Deny by default; AGENTS.md, regra 4).

O teste percorre todas as rotas do app, não só as de `/api/v1`, e classifica cada uma:

- protegida: alguma dependência dela, direta ou aninhada, é um `require("recurso:acao")`;
- pública: está em `ROTAS_PUBLICAS`, com a justificativa e a spec que a decidiu;
- só autenticada: está em `ROTAS_SO_AUTENTICADAS` (o design pede "autenticado", sem permissão) e
  depende do `CurrentUser` da 002.

Rota nova que não cai em nenhum dos três casos faz o teste falhar. Para torná-la pública ou só
autenticada, a decisão tem de estar no design de uma spec e entrar na lista com a referência.
"""

from collections.abc import Iterator
from typing import Any, get_args

from fastapi import Depends, FastAPI
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute, iter_route_contexts

from src.main import create_app
from src.modules.access.api.deps import require
from src.modules.identity.api.deps import CurrentUser
from tests.factories import make_settings

Rota = tuple[str, str]
"""(método, caminho como declarado), ex.: `("PATCH", "/api/v1/unidades/{id}")`."""

ROTAS_PUBLICAS: dict[Rota, str] = {
    ("GET", "/health/live"): "001/R6, arquitetura § 8: sondas do orquestrador",
    ("GET", "/health/ready"): "001/R6, arquitetura § 8: sondas do orquestrador",
    ("GET", "/.well-known/jwks.json"): "002, arquitetura § 8: chaves públicas do JWT",
    # Documentação OpenAPI: só existe fora de produção (001/R6.3, `create_app`).
    ("GET", "/openapi.json"): "001/R6.3: contrato, só em dev e test",
    ("HEAD", "/openapi.json"): "001/R6.3: contrato, só em dev e test",
    ("GET", "/docs"): "001/R6.3: Swagger UI, só em dev e test",
    ("HEAD", "/docs"): "001/R6.3: Swagger UI, só em dev e test",
    ("GET", "/docs/oauth2-redirect"): "001/R6.3: Swagger UI, só em dev e test",
    ("HEAD", "/docs/oauth2-redirect"): "001/R6.3: Swagger UI, só em dev e test",
    ("GET", "/redoc"): "001/R6.3: ReDoc, só em dev e test",
    ("HEAD", "/redoc"): "001/R6.3: ReDoc, só em dev e test",
}

_REFERENCIAS = (
    "distritos",
    "areas-tecnicas",
    "tipos-unidade",
    "tipos-equipamento",
    "tipos-servico",
)

ROTAS_SO_AUTENTICADAS: dict[Rota, str] = {
    ("GET", "/api/v1/me"): "003/R5.1, design da 003 § Rotas: autenticado",
    **{
        ("GET", f"/api/v1/referencias/{tabela}"): "006/R7.1, design da 006 § Rotas: autenticado"
        for tabela in _REFERENCIAS
    },
}

_TIPO_DO_REQUIRE = type(require("recurso:acao"))
_USUARIO_ATUAL = get_args(CurrentUser)[1].dependency


def _dependencias(dependant: Dependant) -> Iterator[Any]:
    for dependencia in dependant.dependencies:
        yield dependencia.call
        yield from _dependencias(dependencia)


def _rotas(app: FastAPI) -> Iterator[tuple[Rota, Dependant | None]]:
    """Cada (método, caminho) do app com o `Dependant` da rota (None fora das rotas da API)."""
    for contexto in iter_route_contexts(app.routes):
        rota = contexto.original_route
        dependant = contexto.dependant if isinstance(rota, APIRoute) else None
        for metodo in sorted(contexto.methods or {"*"}):
            yield (metodo, str(contexto.path)), dependant


def _permissoes(dependant: Dependant | None) -> list[str]:
    if dependant is None:
        return []
    return [d.permissao for d in _dependencias(dependant) if isinstance(d, _TIPO_DO_REQUIRE)]


def _autentica(dependant: Dependant | None) -> bool:
    return dependant is not None and _USUARIO_ATUAL in _dependencias(dependant)


def rotas_desprotegidas(app: FastAPI) -> list[str]:
    """As rotas que não declaram permissão nem estão, como devem, numa das listas."""
    problemas = []
    for rota, dependant in _rotas(app):
        metodo, caminho = rota
        permissoes = _permissoes(dependant)
        if any(not p or ":" not in p for p in permissoes):
            problemas.append(f"{metodo} {caminho}: permissão fora do formato recurso:acao")
        elif permissoes or rota in ROTAS_PUBLICAS:
            continue
        elif rota in ROTAS_SO_AUTENTICADAS:
            if not _autentica(dependant):
                problemas.append(f"{metodo} {caminho}: listada como autenticada, sem CurrentUser")
        else:
            problemas.append(f"{metodo} {caminho}: sem require() e fora das listas")
    return problemas


def test_toda_rota_declara_permissao_ou_esta_numa_lista_explicita() -> None:
    """003/R4.1"""
    problemas = rotas_desprotegidas(create_app(make_settings()))
    assert not problemas, "Rotas sem permissão declarada (AGENTS.md, regra 4):\n" + "\n".join(
        problemas
    )


def test_o_teste_reconhece_rota_desprotegida() -> None:
    """003/R4.1: o detector acusa rota sem `require`, e só autenticada fora da lista."""
    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)

    @app.get("/api/v1/aberta")
    async def aberta() -> None: ...

    @app.get("/api/v1/so-login")
    async def so_login(_usuario: CurrentUser) -> None: ...

    @app.get("/api/v1/me")
    async def me_sem_login() -> None: ...

    @app.get("/api/v1/protegida", dependencies=[Depends(require("coisa:read"))])
    async def protegida() -> None: ...

    @app.get("/api/v1/sem-formato", dependencies=[Depends(require("coisa"))])
    async def sem_formato() -> None: ...

    assert rotas_desprotegidas(app) == [
        "GET /api/v1/aberta: sem require() e fora das listas",
        "GET /api/v1/so-login: sem require() e fora das listas",
        "GET /api/v1/me: listada como autenticada, sem CurrentUser",
        "GET /api/v1/sem-formato: permissão fora do formato recurso:acao",
    ]
