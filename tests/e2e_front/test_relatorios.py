"""Tela Relatórios (spec 014, T2: R1.2 a R1.7, R2.1, R2.2, R2.5).

Contra o compose com SeaweedFS. Só os estados que o laboratório não produz (503, `falhou`) ou
não segura por tempo bastante (`pendente`) são simulados por `page.route` (R6.2).
"""

import json
import re
import time
from collections.abc import Callable
from typing import Any

from playwright.sync_api import Page, Request, Route, expect

from tests.e2e_front.apoio import api as _api
from tests.e2e_front.apoio import token as _token

Sessao = Callable[[str], Page]
LISTA = re.compile(r"/api/v1/relatorios(\?|$)")
ID_FALSO = "00000000-0000-7000-8000-0000000000aa"


def _abrir(pagina: Page) -> None:
    with pagina.expect_response(LISTA):
        pagina.goto("/#/relatorios")
    expect(pagina.locator("[data-ref=relatorios], [data-estado=vazio]").first).to_be_visible()


def _json(rota: Route, corpo: object, status: int = 200) -> None:
    tipo = "application/problem+json" if status >= 400 else "application/json"
    rota.fulfill(status=status, content_type=tipo, body=json.dumps(corpo))


def _pedido(status: str, **extra: Any) -> dict[str, Any]:
    return {
        "id": ID_FALSO,
        "tipo": "inventario_unidades",
        "formato": "csv",
        "filtros": {
            "distrito_id": None,
            "area_tecnica_id": None,
            "tipo_unidade_id": None,
            "status": "ativa",
        },
        "status": status,
        "solicitado_por": "00000000-0000-7000-8000-0000000000bb",
        "criado_em": "2026-11-26T12:00:00Z",
        "concluido_em": None,
        "tamanho_bytes": None,
        "vence_em": None,
        "vencido": False,
        "erro": None,
        "integridade": None,
        **extra,
    }


def _pagina_com(*itens: dict[str, Any]) -> dict[str, Any]:
    return {"itens": list(itens), "total": len(itens), "pagina": 1, "tamanho": 20}


def test_diretoria_nao_ve_trilha(sessao_de: Sessao) -> None:
    """R1.3: a trilha só para quem tem `auditoria:read`; o inventário para `unidade:read`."""
    diretoria = sessao_de("DIRETORIA")
    _abrir(diretoria)
    tipo = diretoria.locator("#relForm select[name=tipo]")
    expect(tipo.locator("option", has_text="Inventário de unidades")).to_have_count(1)
    expect(tipo.locator("option", has_text="Trilha de auditoria")).to_have_count(0)

    gestor = sessao_de("GESTOR_DADOS")
    _abrir(gestor)
    expect(
        gestor.locator("#relForm select[name=tipo] option", has_text="Trilha de auditoria")
    ).to_have_count(1)


def test_pedido_de_inventario_conclui_sem_clique(sessao_de: Sessao) -> None:
    """R1.2, R1.4, R2.1, R2.2: o pedido entra `pendente` e vira `concluido` sem clique."""
    pagina = sessao_de("GESTOR_DADOS")
    token = _token(pagina)
    distrito = _api(pagina, token, "/referencias/distritos")[0]
    eu = _api(pagina, token, "/me")["id"]

    # A geração do inventário do seed termina antes da primeira recarga: a primeira lista depois
    # do pedido vem da API, só com o status do pedido novo trocado para `pendente` (R6.2).
    antigos: set[str] = set()
    estado: dict[str, Any] = {"enviado": False, "forcado": None}

    def lista(rota: Route) -> None:
        if rota.request.method != "GET":
            rota.fallback()
            return
        resposta = rota.fetch()
        corpo = resposta.json()
        itens = corpo["itens"]
        if not estado["enviado"]:
            antigos.update(i["id"] for i in itens)
        elif estado["forcado"] is None and itens and itens[0]["id"] not in antigos:
            estado["forcado"] = itens[0]["id"]
            itens[0].update(status="pendente", concluido_em=None, integridade=None)
        rota.fulfill(response=resposta, json=corpo)

    pagina.route(LISTA, lista)
    _abrir(pagina)
    form = pagina.locator("#relForm")
    form.locator("select[name=tipo]").select_option("inventario_unidades")
    form.locator("select[name=formato]").select_option("csv")
    form.locator("select[name=distrito_id]").select_option(str(distrito["id"]))
    estado["enviado"] = True
    with pagina.expect_response(
        lambda r: r.request.method == "POST" and LISTA.search(r.url) is not None
    ) as resposta:
        form.locator("button[type=submit]").click()
    assert resposta.value.status == 202
    assert resposta.value.request.post_data_json == {
        "tipo": "inventario_unidades",
        "formato": "csv",
        "filtros": {"distrito_id": distrito["id"]},
    }
    criado = {"id": resposta.value.json()["id"]}
    expect(pagina.locator(".toast", has_text="Relatório pedido")).to_be_visible()

    linha = pagina.locator(f"[data-ref=relatorios] tr[data-id='{criado['id']}']")
    expect(linha.locator("[data-ref=situacao]")).to_have_text("Pendente")
    expect(pagina.locator("[data-ref=auto]")).to_have_text("Atualização automática ligada")
    expect(linha.locator("[data-ref=situacao]")).to_have_text("Concluído", timeout=20_000)
    expect(pagina.locator("[data-ref=auto]")).to_have_text("Atualização automática desligada")
    assert estado["forcado"] == criado["id"]
    expect(linha).to_contain_text("Inventário de unidades")
    expect(linha).to_contain_text("CSV")
    expect(linha).to_contain_text(distrito["nome"])
    expect(linha).to_contain_text("Você")
    real = _api(pagina, token, f"/relatorios/{criado['id']}")
    assert real["solicitado_por"] == eu
    assert real["status"] == "concluido"


def test_periodo_longo_mostra_erro_no_campo(sessao_de: Sessao) -> None:
    """R1.5, R1.6: o 422 da API cai no campo `ate` (último segmento do `campo`)."""
    pagina = sessao_de("GESTOR_DADOS")
    _abrir(pagina)
    form = pagina.locator("#relForm")
    form.locator("select[name=tipo]").select_option("trilha_auditoria")
    expect(form.locator("[name=distrito_id]")).to_be_hidden()
    form.locator("input[name=de]").fill("2024-01-01")
    form.locator("input[name=ate]").fill("2025-06-30")
    with pagina.expect_response(
        lambda r: r.request.method == "POST" and LISTA.search(r.url) is not None
    ) as resposta:
        form.locator("button[type=submit]").click()
    assert resposta.value.status == 422
    campos = [e["campo"] for e in resposta.value.json()["errors"]]
    assert any(c.endswith(".ate") for c in campos), campos
    caixa = form.locator("[data-campo=ate]")
    expect(caixa).to_have_class(re.compile(r"\bbad\b"))
    expect(caixa.locator(".fld-err")).to_contain_text("366 dias")

    # Erro local do período (inicial depois da final): no campo, sem chamar a API.
    posts: list[Request] = []
    pagina.on("request", lambda r: posts.append(r) if r.method == "POST" else None)
    form.locator("input[name=de]").fill("2025-02-01")
    form.locator("input[name=ate]").fill("2025-01-01")
    form.locator("button[type=submit]").click()
    expect(caixa.locator(".fld-err")).to_contain_text("anterior ou igual")
    assert posts == []


def test_atualizacao_para_ao_sair(sessao_de: Sessao) -> None:
    """R2.2: com pedido pendente a lista recarrega a cada 3 s, e para ao sair da tela."""
    pagina = sessao_de("GESTOR_DADOS")
    chamadas: list[float] = []

    def lista(rota: Route) -> None:
        chamadas.append(time.monotonic())
        _json(rota, _pagina_com(_pedido("pendente")))

    pagina.route(LISTA, lista)
    _abrir(pagina)
    expect(pagina.locator("[data-ref=auto]")).to_have_text("Atualização automática ligada")
    expect(pagina.locator(f"tr[data-id='{ID_FALSO}'] [data-ref=situacao]")).to_have_text("Pendente")
    with pagina.expect_request(LISTA, timeout=6000):
        pass  # a recarga automática chega em ~3 s
    pagina.goto("/#/unidades")
    expect(pagina.locator("h1")).to_contain_text("Unidades")
    antes = len(chamadas)
    pagina.wait_for_timeout(4500)
    assert len(chamadas) == antes, "a lista continuou recarregando depois de sair da tela"


def test_exportacao_desligada_503(sessao_de: Sessao) -> None:
    """R1.7: 503 no pedido informa que a exportação não está configurada."""
    pagina = sessao_de("GESTOR_DADOS")

    def pedido(rota: Route) -> None:
        if rota.request.method != "POST":
            rota.fallback()
            return
        _json(rota, {"title": "Serviço indisponível", "status": 503}, 503)

    pagina.route(LISTA, pedido)
    _abrir(pagina)
    pagina.locator("#relForm select[name=tipo]").select_option("inventario_unidades")
    pagina.locator("#relForm button[type=submit]").click()
    expect(pagina.locator("#rel-geral")).to_have_text(
        "A exportação de relatórios não está configurada neste servidor."
    )


def test_falhou_permite_pedir_de_novo(sessao_de: Sessao) -> None:
    """R2.5: `falhou` mostra a mensagem genérica e repete o pedido com os mesmos filtros."""
    pagina = sessao_de("GESTOR_DADOS")
    mensagem = "Não foi possível gerar o relatório. Peça de novo."
    falho = _pedido("falhou", erro=mensagem, formato="xlsx")

    def lista(rota: Route) -> None:
        if rota.request.method == "GET":
            _json(rota, _pagina_com(falho))
        else:
            rota.fallback()  # o novo pedido vai à API de verdade

    pagina.route(LISTA, lista)
    _abrir(pagina)
    linha = pagina.locator(f"tr[data-id='{ID_FALSO}']")
    expect(linha.locator("[data-ref=situacao]")).to_have_text("Falhou")
    expect(linha.locator("[data-ref=erro]")).to_have_text(mensagem)
    expect(linha.get_by_role("button", name="Baixar")).to_have_count(0)
    with pagina.expect_response(
        lambda r: r.request.method == "POST" and LISTA.search(r.url) is not None
    ) as resposta:
        linha.get_by_role("button", name="Pedir de novo").click()
    assert resposta.value.status == 202
    assert resposta.value.request.post_data_json == {
        "tipo": falho["tipo"],
        "formato": falho["formato"],
        "filtros": falho["filtros"],
    }
    expect(pagina.locator(".toast", has_text="Relatório pedido")).to_be_visible()
