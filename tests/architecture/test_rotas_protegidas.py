"""Toda rota de /api/v1 declara permissão ou está na lista de rotas públicas (003/T5; R4.1).

AGENTS.md, regra 4 (deny by default). Percorre as dependências de cada rota, recursivamente, em
busca do `require()` ou do `autenticado()` do módulo de acesso.
"""

from collections.abc import Sequence

from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute
from starlette.routing import BaseRoute

from src.main import create_app
from src.modules.access.api.deps import _Autenticacao, _Exigencia
from tests.factories import make_settings

# Lista explícita (design da 002 § Decisões): login, 2FA e refresh não têm usuário ainda; o
# logout autentica pelo Bearer (`CurrentUser`), sem permissão.
PUBLICAS = {
    "/api/v1/auth/login",
    "/api/v1/auth/mfa/enroll",
    "/api/v1/auth/mfa/confirm",
    "/api/v1/auth/mfa/verify",
    "/api/v1/auth/refresh",
    "/api/v1/auth/logout",
    # Spec 004 (design § Rotas): `provedores` só diz se cada origem de login está ligada;
    # `oidc/login` e `oidc/callback` acontecem antes de existir usuário (o callback confere o
    # `state` de uso único preso ao navegador, R3.7).
    "/api/v1/auth/provedores",
    "/api/v1/auth/oidc/login",
    "/api/v1/auth/oidc/callback",
    # Fora de /api/v1, como o JWKS da 002, mas listada para registrar a justificativa: só publica
    # chaves públicas, para quem recebe um relatório conferir a assinatura sem conta na
    # plataforma (design da 005, § Rotas e § Segurança; R5.4).
    "/.well-known/relatorios-jwks.json",
}


def _rotas(rotas: Sequence[BaseRoute], prefixo: str = "") -> list[tuple[str, APIRoute]]:
    """As `APIRoute` do app com o caminho completo. Nesta versão do FastAPI, `include_router`
    guarda um roteador incluído (`original_router`) em vez de copiar as rotas para o app."""
    encontradas: list[tuple[str, APIRoute]] = []
    for rota in rotas:
        if isinstance(rota, APIRoute):
            encontradas.append((prefixo + rota.path, rota))
        incluido = getattr(rota, "original_router", None)
        if incluido is not None:
            contexto = getattr(rota, "include_context", None)
            encontradas.extend(_rotas(incluido.routes, prefixo + getattr(contexto, "prefix", "")))
    return encontradas


def _protecao(dependencia: Dependant) -> list[object]:
    encontradas: list[object] = []
    if isinstance(dependencia.call, _Exigencia | _Autenticacao):
        encontradas.append(dependencia.call)
    for sub in dependencia.dependencies:
        encontradas.extend(_protecao(sub))
    return encontradas


def test_toda_rota_da_api_declara_permissao_ou_e_publica() -> None:
    app = create_app(make_settings())
    rotas = _rotas(app.routes)
    sem_protecao = [
        f"{sorted(rota.methods or ())} {caminho}"
        for caminho, rota in rotas
        if caminho.startswith("/api/v1")
        and caminho not in PUBLICAS
        and not _protecao(rota.dependant)
    ]

    assert len([c for c, _ in rotas if c.startswith("/api/v1")]) > 40  # o teste viu as rotas
    assert sem_protecao == []


def test_lista_publica_so_tem_rotas_que_existem() -> None:
    app = create_app(make_settings())
    caminhos = {caminho for caminho, _ in _rotas(app.routes)}

    assert caminhos >= PUBLICAS


def test_so_o_me_dispensa_permissao_especifica() -> None:
    """`autenticado()` só no `GET /me` (003/R5.1); o resto exige permissão (`require`)."""
    app = create_app(make_settings())
    so_autenticadas = [
        caminho
        for caminho, rota in _rotas(app.routes)
        if _protecao(rota.dependant)
        and all(isinstance(p, _Autenticacao) for p in _protecao(rota.dependant))
    ]

    assert so_autenticadas == ["/api/v1/me"]
