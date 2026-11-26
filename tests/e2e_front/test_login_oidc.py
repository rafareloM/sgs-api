"""Entrada OIDC na tela de login (spec 004, T10: R3.9; design § Front-end).

A rota `GET /api/v1/auth/provedores` só chega na 004/T7: aqui a API é simulada por `page.route`.
"""

import json
from collections.abc import Callable

import pytest
from playwright.sync_api import Page, Route, expect

from tests.e2e_front.conftest import BASE

ENTRADA = "Entrar pelo provedor de identidade"
MENSAGEM_DE_ERRO = "Não foi possível entrar pelo provedor de identidade. Tente de novo."
ME_FICTICIO: dict[str, object] = {
    "id": "00000000-0000-7000-8000-000000000002",
    "username": "pessoa.oidc",
    "nome": "Pessoa do Provedor",
    "email": None,
    "origem": "oidc",
    "papeis": [],
    "permissoes": {},
}


def _json(corpo: object, status: int = 200) -> Callable[[Route], None]:
    return lambda rota: rota.fulfill(
        status=status, content_type="application/json", body=json.dumps(corpo)
    )


def _provedores(pagina: Page, oidc: bool) -> list[str]:
    """Simula `/auth/provedores` e devolve a lista de chamadas recebidas."""
    chamadas: list[str] = []

    def responder(rota: Route) -> None:
        chamadas.append(rota.request.method)
        _json({"ldap": False, "oidc": oidc})(rota)

    pagina.route("**/api/v1/auth/provedores", responder)
    return chamadas


def test_com_oidc_ligado_o_login_oferece_a_entrada_pelo_provedor(pagina_anonima: Page) -> None:
    """004/R3.9"""
    pagina = pagina_anonima
    chamadas = _provedores(pagina, oidc=True)
    pagina.goto("/")

    entrada = pagina.get_by_role("link", name=ENTRADA)
    expect(entrada).to_be_visible()
    expect(entrada).to_have_attribute("href", "/api/v1/auth/oidc/login")
    expect(pagina.locator("#loginForm").get_by_role("link", name=ENTRADA)).to_have_count(0)

    # Redesenhar a tela (erro de preenchimento) mantém a entrada sem consultar a API de novo.
    pagina.click("#loginForm button[type=submit]")
    expect(pagina.locator(".err-summary")).to_have_text("Preencha usuário e senha.")
    expect(entrada).to_be_visible()
    assert chamadas == ["GET"]


def test_com_oidc_desligado_o_login_nao_oferece_a_entrada(pagina_anonima: Page) -> None:
    """004/R3.9"""
    pagina = pagina_anonima
    chamadas = _provedores(pagina, oidc=False)
    pagina.goto("/")
    expect(pagina.locator("#loginForm")).to_be_visible()
    pagina.wait_for_load_state("networkidle")  # a resposta dos provedores já foi tratada
    assert chamadas == ["GET"]
    expect(pagina.get_by_role("link", name=ENTRADA)).to_have_count(0)


@pytest.mark.parametrize(
    "resposta",
    [
        pytest.param(lambda rota: rota.abort(), id="sem-rede"),
        pytest.param(
            _json({"title": "Not Found", "status": 404, "detail": "Not Found"}, 404), id="404"
        ),
        pytest.param(
            lambda rota: rota.fulfill(status=200, content_type="text/html", body="<!doctype html>"),
            id="resposta-inesperada",
        ),
    ],
)
def test_sem_resposta_valida_dos_provedores_o_login_segue_so_com_senha(
    pagina_anonima: Page, resposta: Callable[[Route], None]
) -> None:
    """004/R3.9: a falha da consulta não quebra a tela nem mostra erro; só não há a entrada."""
    pagina = pagina_anonima
    erros: list[str] = []
    pagina.on("pageerror", lambda erro: erros.append(str(erro)))
    pagina.route("**/api/v1/auth/provedores", resposta)
    with pagina.expect_request("**/api/v1/auth/provedores"):
        pagina.goto("/")
    expect(pagina.locator("#loginForm")).to_be_visible()
    pagina.wait_for_load_state("networkidle")
    expect(pagina.get_by_role("link", name=ENTRADA)).to_have_count(0)
    expect(pagina.locator(".err-summary")).to_have_count(0)
    expect(pagina.locator("#lg-user")).to_be_enabled()
    assert erros == []


def test_retorno_com_login_erro_oidc_mostra_a_mensagem_e_limpa_a_url(
    pagina_anonima: Page,
) -> None:
    """004/R3.9, R3.5: código de erro genérico; a mensagem não traz detalhe do provedor."""
    pagina = pagina_anonima
    _provedores(pagina, oidc=True)
    pagina.goto("/?login_erro=oidc")

    expect(pagina.locator(".err-summary")).to_have_text(MENSAGEM_DE_ERRO)
    expect(pagina).to_have_url(f"{BASE}/")
    expect(pagina.get_by_role("link", name=ENTRADA)).to_be_visible()  # tentar de novo


def test_retorno_com_sucesso_abre_a_sessao_pela_renovacao(pagina_anonima: Page) -> None:
    """004/R3.9, R3.4: sem token na URL; o cookie do callback abre a sessão pelo refresh."""
    pagina = pagina_anonima
    vistos: list[str] = []

    def me(rota: Route) -> None:
        vistos.append(rota.request.headers.get("authorization", ""))
        _json(ME_FICTICIO)(rota)

    _provedores(pagina, oidc=True)
    pagina.route(
        "**/api/v1/auth/refresh", _json({"access_token": "token-do-refresh", "expires_in": 900})
    )
    pagina.route("**/api/v1/me", me)
    pagina.goto("/")

    expect(pagina.locator(".shell")).to_be_visible()
    assert vistos == ["Bearer token-do-refresh"]
