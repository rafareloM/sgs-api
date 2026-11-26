"""Rotas do login OIDC e dos provedores (spec 004, T7; design § Rotas e § Fluxo, Login OIDC).

As três são públicas (`tests/architecture/test_rotas_protegidas.py`, `PUBLICAS`): `provedores` só
diz se cada origem está ligada; `oidc/login` e `oidc/callback` acontecem antes de existir usuário.

O callback responde sempre 302, nunca JSON: para `FRONTEND_URL` com o cookie de refresh, ou para
`FRONTEND_URL?login_erro=oidc` (R3.4, R3.5). Nenhum token vai na URL; o front abre a sessão pela
renovação que já faz na abertura (R3.9).
"""

import logging
from typing import Annotated, Any, Final

from fastapi import APIRouter, Cookie, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from src.core.errors import NotFound
from src.core.problem import PROBLEM_JSON
from src.modules.identity.api.auth import CAMINHO_DO_COOKIE, COOKIE, _deps, _origem
from src.modules.identity.application.login import Identidade, Origem, TokensEmitidos, auditar
from src.modules.identity.application.login_oidc import (
    Oidc,
    RecusaOidc,
    concluir_login_oidc,
    consumir_pedido,
    iniciar_login_oidc,
)

router = APIRouter(prefix="/api/v1/auth", tags=["autenticação"])

COOKIE_DE_VINCULO: Final = "sgs_oidc"
CAMINHO_DO_VINCULO: Final = "/api/v1/auth/oidc"
VALIDADE_DO_VINCULO: Final = 600  # o mesmo prazo do pedido no banco (10 min)
ERRO_DE_LOGIN: Final = "login_erro=oidc"
# Os parâmetros do provedor chegam pela URL e vão só para o banco e o adaptador; um valor muito
# longo é recusado como `state` desconhecido, sem 422 (o callback nunca responde JSON).
PARAMETRO_MAX: Final = 4096

_log = logging.getLogger("sgs_api.oidc")


class ProvedoresOut(BaseModel):
    ldap: bool
    oidc: bool


def _oidc(request: Request, sessao: Any) -> Oidc:
    estado = request.app.state
    return Oidc(
        porta=estado.oidc,
        pedidos=estado.repositorio_de_login_oidc(sessao),
        diretorio=estado.repositorio_do_diretorio(sessao),
        mapeamentos=estado.repositorio_de_mapeamentos(sessao),
        atribuicoes=estado.repositorio_de_atribuicoes(sessao),
        permissoes=estado.repositorio_de_permissoes(sessao),
    )


def _sem_cache(resposta: RedirectResponse) -> RedirectResponse:
    resposta.headers["Cache-Control"] = "no-store"
    resposta.headers["Referrer-Policy"] = "no-referrer"
    return resposta


@router.get("/provedores", summary="Origens de login ligadas")
async def provedores(request: Request) -> ProvedoresOut:
    """R3.9: a tela de login mostra a entrada OIDC só com o OIDC ligado."""
    estado = request.app.state
    return ProvedoresOut(ldap=estado.diretorio is not None, oidc=estado.oidc is not None)


@router.get(
    "/oidc/login",
    summary="Começar o login pelo provedor de identidade",
    status_code=302,
    response_class=RedirectResponse,
    responses={
        302: {"description": "Para o provedor, com o cookie de vínculo `sgs_oidc`"},
        404: {"description": "OIDC não configurado", "content": {PROBLEM_JSON: {}}},
        429: {"description": "Limite de 20 por minuto por IP", "content": {PROBLEM_JSON: {}}},
        503: {"description": "Provedor indisponível", "content": {PROBLEM_JSON: {}}},
    },
)
async def login_oidc(request: Request) -> RedirectResponse:
    """R3.1, R3.8: Authorization Code com PKCE S256, `state` e `nonce`; o `redirect_uri` vem da
    configuração."""
    estado = request.app.state
    porta = estado.oidc
    if porta is None:
        raise NotFound("Login pelo provedor de identidade não configurado.")
    origem = _origem(request)
    # Cada chamada grava uma linha: limite próprio, separado do login com senha.
    estado.limite_de_oidc.conferir(origem.ip or "desconhecido")
    async with estado.sessoes() as sessao, sessao.begin():
        inicio = await iniciar_login_oidc(
            _oidc(request, sessao), porta, deps=_deps(request, sessao)
        )
    resposta = RedirectResponse(inicio.url, status_code=302)
    resposta.set_cookie(
        COOKIE_DE_VINCULO,
        inicio.vinculo,
        max_age=VALIDADE_DO_VINCULO,
        path=CAMINHO_DO_VINCULO,
        secure=True,
        httponly=True,
        # A volta do provedor é uma navegação de nível superior entre sites: `Strict` não mandaria
        # o cookie.
        samesite="lax",
    )
    return _sem_cache(resposta)


@router.get(
    "/oidc/callback",
    summary="Retorno do provedor de identidade",
    status_code=302,
    response_class=RedirectResponse,
    responses={302: {"description": "Para o front, com a sessão ou com `login_erro=oidc`"}},
)
async def callback_oidc(
    request: Request,
    code: Annotated[str | None, Query()] = None,
    state: Annotated[str | None, Query()] = None,
    error: Annotated[str | None, Query()] = None,
    vinculo: Annotated[str | None, Cookie(alias=COOKIE_DE_VINCULO)] = None,
) -> RedirectResponse:
    """R3.2 a R3.7, R4.3, R4.4: sempre 302, nunca JSON."""
    estado = request.app.state
    porta, destino = estado.oidc, estado.settings.frontend_url
    if porta is None or destino is None:
        raise NotFound("Login pelo provedor de identidade não configurado.")
    origem = _origem(request)
    if any(valor is not None and len(valor) > PARAMETRO_MAX for valor in (code, state, error)):
        state = None
    try:
        # Passo 1: transação própria, confirmada antes da troca.
        async with estado.sessoes() as sessao, sessao.begin():
            consumido = await consumir_pedido(
                state,
                vinculo,
                pedidos=estado.repositorio_de_login_oidc(sessao),
                agora=_deps(request, sessao).relogio(),
            )
        if isinstance(consumido, RecusaOidc):
            return await _recusar(request, origem, consumido, destino)
        async with estado.sessoes() as sessao, sessao.begin():
            deps = _deps(request, sessao)
            resultado = await concluir_login_oidc(
                consumido,
                code,
                error,
                oidc=_oidc(request, sessao),
                porta=porta,
                origem=origem,
                deps=deps,
            )
            if isinstance(resultado, RecusaOidc):
                # Nada de provisionamento foi gravado antes da recusa: a auditoria vai junto.
                await _auditar_recusa(deps, origem, resultado)
    except Exception as erro:
        # Só o tipo: a mensagem pode trazer dados do provedor. O pedido já está usado (passo 1).
        _log.error("login OIDC falhou: %s", type(erro).__name__)
        return await _recusar(request, origem, RecusaOidc("troca"), destino)
    if isinstance(resultado, RecusaOidc):
        return _para_o_front(destino, erro=True)
    return _com_sessao(_para_o_front(destino, erro=False), resultado)


async def _recusar(
    request: Request, origem: Origem, recusa: RecusaOidc, destino: str
) -> RedirectResponse:
    async with request.app.state.sessoes() as sessao, sessao.begin():
        await _auditar_recusa(_deps(request, sessao), origem, recusa)
    return _para_o_front(destino, erro=True)


async def _auditar_recusa(deps: Identidade, origem: Origem, recusa: RecusaOidc) -> None:
    """R3.5: `auth.oidc_failed` com o motivo e o `sub` quando houver; nunca o código nem o token."""
    detalhes = {"motivo": recusa.motivo} | ({"sub": recusa.sub} if recusa.sub else {})
    await auditar(deps, "auth.oidc_failed", origem, recusa.usuario_id, detalhes)


def _para_o_front(destino: str, *, erro: bool) -> RedirectResponse:
    resposta = RedirectResponse(f"{destino}?{ERRO_DE_LOGIN}" if erro else destino, status_code=302)
    resposta.delete_cookie(COOKIE_DE_VINCULO, path=CAMINHO_DO_VINCULO, secure=True, httponly=True)
    return _sem_cache(resposta)


def _com_sessao(resposta: RedirectResponse, tokens: TokensEmitidos) -> RedirectResponse:
    """R3.4: só o cookie de refresh, como `_com_cookie` da 002; o access token não sai da API."""
    resposta.set_cookie(
        COOKIE,
        tokens.refresh_token,
        expires=tokens.refresh_expira_em,
        path=CAMINHO_DO_COOKIE,
        secure=True,
        httponly=True,
        samesite="strict",
    )
    return resposta
