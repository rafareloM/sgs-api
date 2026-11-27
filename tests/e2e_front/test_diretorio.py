"""Tela Diretório (spec 014, R4 e R5; design § Diretório): execuções da sincronização LDAP e
mapeamentos grupo→papel, contra o compose com o `slapd` de laboratório."""

import json
import time
from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from tests.e2e_front.apoio import api, requisicao, token


def test_abas_conforme_permissao(sessao_de: Callable[[str], Page]) -> None:
    """R4.1: o Admin TI vê Execuções e Grupos; `#/diretorio` abre a primeira aba."""
    pagina = sessao_de("ADMIN_TI")
    pagina.goto("/#/diretorio")
    expect(pagina).to_have_url("https://localhost:18444/#/diretorio/execucoes")
    abas = pagina.locator("nav.tabs a")
    expect(abas).to_have_text(["Execuções", "Grupos"])
    expect(pagina.locator("nav.tabs a.on")).to_have_attribute("data-aba", "execucoes")
    pagina.click("nav.tabs a[data-aba=grupos]")
    expect(pagina.locator("nav.tabs a.on")).to_have_attribute("data-aba", "grupos")


@pytest.mark.parametrize("papel", ["GESTOR_DADOS", "AUDITOR"])
def test_sem_permissao_do_diretorio_mostra_sem_acesso(
    sessao_de: Callable[[str], Page], papel: str
) -> None:
    """R4.1: sem `diretorio:sync` nem `papel:assign`, a tela diz "sem acesso"."""
    pagina = sessao_de(papel)
    pagina.goto("/#/diretorio/grupos")
    expect(pagina.locator("[data-estado=sem-acesso]")).to_be_visible()


# --- T4: execuções e sincronização (R4.2 a R4.6) ---

EXECUCOES = "/#/diretorio/execucoes"


def _por_extenso(c: dict[str, int]) -> str:
    return f"{c['criados']} criados, {c['atualizados']} atualizados, {c['desativados']} desativados"


def _curta(c: dict[str, int]) -> str:
    """Como a tela: `+criados ~atualizados` e os desativados com o sinal de menos U+2212."""
    return f"+{c['criados']} ~{c['atualizados']} \u2212{c['desativados']}"


def _sincronizacao_concluida(pagina: Page, token_: str) -> dict[str, Any]:
    """Garante uma execução terminada, sem depender da ordem das suítes (aceita o 409)."""
    resposta = requisicao(pagina, token_, "POST", "/admin/diretorio/sincronizar")
    assert resposta.status in (202, 409), resposta.text()
    for _ in range(60):
        ultima: dict[str, Any] = api(pagina, token_, "/admin/diretorio/execucoes?tamanho=1")[
            "itens"
        ][0]
        if ultima["status"] != "em_andamento":
            return ultima
        time.sleep(1)
    pytest.fail("a sincronização não terminou em 60 s")


def _abrir_execucoes(pagina: Page) -> None:
    """O início do Admin TI já é esta aba: o `goto` sozinho não redesenha, então recarrega."""
    pagina.goto(EXECUCOES)
    pagina.reload()


def _simular_post(pagina: Page, status: int, detalhe: str) -> None:
    pagina.route(
        "**/api/v1/admin/diretorio/sincronizar",
        lambda rota: rota.fulfill(
            status=status,
            content_type="application/problem+json",
            body=json.dumps({"status": status, "title": "Erro", "detail": detalhe}),
        ),
    )


def test_sincronizar_agora_conclui_e_mostra_contagens(sessao_de: Callable[[str], Page]) -> None:
    """R4.2, R4.4, R4.6: o clique cria a execução, a lista se atualiza sozinha até "Concluída"
    e mostra as contagens da API, com quem disparou."""
    pagina = sessao_de("ADMIN_TI")
    token_ = token(pagina)
    _sincronizacao_concluida(pagina, token_)  # outra suíte pode ter deixado uma em andamento
    _abrir_execucoes(pagina)
    expect(pagina.locator("table[data-ref=execucoes]")).to_be_visible()
    with pagina.expect_response("**/api/v1/admin/diretorio/sincronizar") as resposta:
        pagina.click("#dir-sincronizar")
    assert resposta.value.status == 202
    execucao_id = resposta.value.json()["execucao_id"]
    expect(pagina.locator(".toast.ok", has_text="Sincronização iniciada")).to_be_visible()
    linha = pagina.locator(f"table[data-ref=execucoes] tr[data-id='{execucao_id}']")
    expect(linha.locator("[data-ref=situacao]")).to_have_text("Concluída", timeout=60_000)

    execucao = api(pagina, token_, f"/admin/diretorio/execucoes/{execucao_id}")
    assert execucao["status"] == "concluida"
    for chave in ("usuarios", "grupos"):
        celula = linha.locator(f"[data-ref={chave}]")
        expect(celula).to_have_text(_curta(execucao[chave]))
        expect(celula).to_have_attribute("title", _por_extenso(execucao[chave]))
    expect(linha.locator("[data-ref=conflitos]")).to_have_text(str(len(execucao["conflitos"])))
    expect(linha.locator("[data-ref=disparada-por]")).to_have_text("Você")


def test_detalhe_da_execucao(sessao_de: Callable[[str], Page]) -> None:
    """R4.5: o modal mostra as contagens por extenso e os conflitos; o erro da API vai num
    banner, escapado (execução que falhou é simulada: o laboratório não a produz)."""
    pagina = sessao_de("ADMIN_TI")
    token_ = token(pagina)
    execucao = _sincronizacao_concluida(pagina, token_)
    _abrir_execucoes(pagina)
    pagina.click(f"tr[data-id='{execucao['id']}'] [data-detalhe]")
    modal = pagina.locator(".modal")
    expect(modal.locator("[data-ref=usuarios]")).to_have_text(_por_extenso(execucao["usuarios"]))
    expect(modal.locator("[data-ref=grupos]")).to_have_text(_por_extenso(execucao["grupos"]))
    expect(modal.locator("table[data-ref=conflitos] tbody tr")).to_have_count(
        len(execucao["conflitos"])
    )
    expect(modal.locator("[data-ref=erro]")).to_have_count(0)
    pagina.click("#ex-fechar")

    falhou = execucao | {
        "status": "falhou",
        "erro": "<b>Falha</b> ao consultar o diretório.",
        "conflitos": [
            {"tipo": "email", "external_id": "uid=x", "usuario_existente_id": execucao["id"]},
        ],
    }
    pagina.route(
        f"**/api/v1/admin/diretorio/execucoes/{execucao['id']}",
        lambda rota: rota.fulfill(
            status=200, content_type="application/json", body=json.dumps(falhou)
        ),
    )
    pagina.click(f"tr[data-id='{execucao['id']}'] [data-detalhe]")
    expect(modal.locator("[data-ref=erro]")).to_have_text("<b>Falha</b> ao consultar o diretório.")
    expect(modal.locator("[data-ref=situacao]")).to_have_text("Falhou")
    conflito = modal.locator("table[data-ref=conflitos] tbody tr")
    expect(conflito).to_have_text(f"E-mail repetidouid=x{execucao['id']}")


def test_sincronizacao_em_andamento_409_vira_aviso(sessao_de: Callable[[str], Page]) -> None:
    """R4.3: o 409 vira aviso (toast), sem erro de tela; botão desabilitado durante o pedido."""
    pagina = sessao_de("ADMIN_TI")
    _simular_post(pagina, 409, "Já há uma sincronização do diretório em andamento.")
    pagina.goto(EXECUCOES)
    botao = pagina.locator("#dir-sincronizar")
    expect(botao).to_be_enabled()
    botao.evaluate(
        """b => { window.desabilitou = false;
        new MutationObserver(() => { if (b.disabled) window.desabilitou = true; })
          .observe(b, { attributes: true }); }"""
    )
    botao.click()
    expect(
        pagina.locator(".toast.wait", has_text="Já há uma sincronização em andamento.")
    ).to_be_visible()
    expect(pagina.locator("#dir-aviso .err-summary")).to_have_count(0)
    expect(botao).to_be_enabled()
    assert pagina.evaluate("window.desabilitou") is True


def test_ldap_desligado_503(sessao_de: Callable[[str], Page]) -> None:
    """R4.3: sem LDAP configurado (503 simulado), a tela diz isso no resumo de erro."""
    pagina = sessao_de("ADMIN_TI")
    _simular_post(pagina, 503, "Sincronização do diretório não configurada.")
    pagina.goto(EXECUCOES)
    pagina.click("#dir-sincronizar")
    expect(pagina.locator("#dir-aviso .err-summary")).to_have_text(
        "O LDAP não está configurado neste servidor."
    )
