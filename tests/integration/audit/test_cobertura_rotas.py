"""Cobertura sistemática da trilha nas rotas de escrita (spec 013, T11; R7.1, R7.2, R7.6).

Um roteiro único chama, em ordem, cada rota de escrita do mapa com dados válidos e confere, no
PostgreSQL, o evento que ela gravou: ação, tipo de ator, origem, resultado, entidade, IP e
User-Agent, e que a ação esperada aparece uma vez só.
"""

from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from fastapi import FastAPI
from sqlalchemy import text

from src.modules.identity.domain.diretorio import DirectorySnapshot
from tests.integration.acesso import (
    GLOBAL,
    Sessoes,
    bearer,
    grupo_espelhado,
    id_pelo_codigo,
    logado,
)
from tests.integration.audit.cobertura import EXCECOES, MAPA, rotas_de_escrita
from tests.integration.identity.autenticacao import codigo, login, segredo_da_uri, usuario_local
from tests.integration.reports.falsos import geracao_falsa

AGENTE = "cobertura-013/1.0"


def test_toda_rota_de_escrita_esta_mapeada(app: FastAPI) -> None:
    """013/R7.1: toda rota de escrita está no mapa ou nas exceções justificadas, e o mapa não
    cita rota que não existe."""
    rotas = rotas_de_escrita(app.routes)

    assert rotas - MAPA.keys() - EXCECOES.keys() == set(), "rota de escrita sem mapa"
    assert (MAPA.keys() | EXCECOES.keys()) - rotas == set(), "mapa com rota inexistente"
    assert not MAPA.keys() & EXCECOES.keys()


class _DiretorioVazio:
    """Diretório LDAP sem ninguém: a sincronização só fecha a execução (004/T4)."""

    async def snapshot(self) -> DirectorySnapshot:
        return DirectorySnapshot(users=(), groups=())


async def _ultimo_id(sessoes: Sessoes) -> int:
    async with sessoes() as sessao:
        return int(await sessao.scalar(text("SELECT coalesce(max(id), 0) FROM audit_log")) or 0)


async def _eventos_depois(sessoes: Sessoes, depois_de: int) -> list[dict[str, Any]]:
    async with sessoes() as sessao:
        linhas = await sessao.execute(
            text(
                "SELECT action, actor_type, origin, result, entity_type, ip, user_agent"
                " FROM audit_log WHERE id > :id ORDER BY id"
            ),
            {"id": depois_de},
        )
        return [dict(linha) for linha in linhas.mappings()]


async def test_rota_grava_evento_completo(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """013/R7.2, R7.6: cada rota do mapa grava a ação esperada, uma vez, com o tipo de ator
    `usuario`, origem `api`, o resultado, a entidade, o IP e o User-Agent da requisição."""
    gestor = bearer(app, await logado(sessoes, ("GESTOR_DADOS", GLOBAL))) | {"User-Agent": AGENTE}
    admin = bearer(app, await logado(sessoes, ("ADMIN_TI", GLOBAL))) | {"User-Agent": AGENTE}
    alvo = await logado(sessoes)
    await usuario_local(sessoes, "cobertura")
    agente = {"User-Agent": AGENTE}
    async with sessoes() as sessao:
        farmacia = await sessao.scalar(text("SELECT id FROM service_types WHERE code = 'FARMACIA'"))
    async with sessoes() as sessao, sessao.begin():
        grupo = await grupo_espelhado(sessao)
    unidade_corpo = {
        "nome": "CAPS Cobertura",
        "tipo_unidade_id": await id_pelo_codigo(sessoes, "tipo_unidade", "CAPS_II"),
        "distrito_id": await id_pelo_codigo(sessoes, "distrito", "DS-I"),
        "cep": "50010100",
        "endereco": "Rua do Sol, 150",
        "status": "ativa",
    }
    ctx: dict[str, Any] = {}
    chamadas: list[tuple[str, Callable[[], Awaitable[httpx.Response]]]] = []

    def passo(chave: str, chamada: Callable[[], Awaitable[httpx.Response]]) -> None:
        chamadas.append((chave, chamada))

    u = "/api/v1/unidades"
    passo("POST /api/v1/unidades", lambda: cliente.post(u, json=unidade_corpo, headers=gestor))
    passo(
        "PATCH /api/v1/unidades/{id}",
        lambda: cliente.patch(
            f"{u}/{ctx['unidade']}", json={"bairro": "Derby"}, headers=gestor | {"If-Match": '"1"'}
        ),
    )
    passo(
        "POST /api/v1/unidades/{id}/equipamentos",
        lambda: cliente.post(
            f"{u}/{ctx['unidade']}/equipamentos",
            json={"nome": "Poli", "tipo_codigo": "POLICLINICA"},
            headers=gestor,
        ),
    )
    passo(
        "PATCH /api/v1/unidades/{id}/equipamentos/{equipamento_id}",
        lambda: cliente.patch(
            f"{u}/{ctx['unidade']}/equipamentos/{ctx['equipamento']}",
            json={"quantidade": 3},
            headers=gestor,
        ),
    )
    passo(
        "POST /api/v1/unidades/{id}/servicos",
        lambda: cliente.post(
            f"{u}/{ctx['unidade']}/servicos",
            json={"nome": "Farmácia", "tipo_servico_id": farmacia},
            headers=gestor,
        ),
    )
    passo(
        "PATCH /api/v1/unidades/{id}/servicos/{servico_id}",
        lambda: cliente.patch(
            f"{u}/{ctx['unidade']}/servicos/{ctx['servico']}",
            json={"no_cnes": True},
            headers=gestor,
        ),
    )
    passo(
        "DELETE /api/v1/unidades/{id}/servicos/{servico_id}",
        lambda: cliente.delete(f"{u}/{ctx['unidade']}/servicos/{ctx['servico']}", headers=gestor),
    )
    passo(
        "DELETE /api/v1/unidades/{id}/equipamentos/{equipamento_id}",
        lambda: cliente.delete(
            f"{u}/{ctx['unidade']}/equipamentos/{ctx['equipamento']}", headers=gestor
        ),
    )
    passo(
        "POST /api/v1/equipamentos",
        lambda: cliente.post(
            "/api/v1/equipamentos",
            json={"nome": "Solto", "tipo_codigo": "POLICLINICA"},
            headers=gestor,
        ),
    )
    passo(
        "PATCH /api/v1/equipamentos/{equipamento_id}",
        lambda: cliente.patch(
            f"/api/v1/equipamentos/{ctx['solto']}", json={"quantidade": 2}, headers=gestor
        ),
    )
    passo(
        "DELETE /api/v1/equipamentos/{equipamento_id}",
        lambda: cliente.delete(f"/api/v1/equipamentos/{ctx['solto']}", headers=gestor),
    )
    passo(
        "POST /api/v1/servicos",
        lambda: cliente.post(
            "/api/v1/servicos", json={"nome": "Solto", "tipo_servico_id": farmacia}, headers=gestor
        ),
    )
    passo(
        "PATCH /api/v1/servicos/{servico_id}",
        lambda: cliente.patch(
            f"/api/v1/servicos/{ctx['servico_solto']}", json={"no_cnes": True}, headers=gestor
        ),
    )
    passo(
        "DELETE /api/v1/servicos/{servico_id}",
        lambda: cliente.delete(f"/api/v1/servicos/{ctx['servico_solto']}", headers=gestor),
    )
    passo(
        "POST /api/v1/referencias/{tipo}",
        lambda: cliente.post(
            "/api/v1/referencias/tipos-equipamento",
            json={"codigo": "AMBULATORIO", "nome": "Ambulatório"},
            headers=gestor,
        ),
    )
    passo(
        "PATCH /api/v1/referencias/{tipo}/{id_}",
        lambda: cliente.patch(
            f"/api/v1/referencias/tipos-equipamento/{ctx['referencia']}",
            json={"nome": "Ambulatório geral"},
            headers=gestor,
        ),
    )
    passo(
        "POST /api/v1/admin/atribuicoes",
        lambda: cliente.post(
            "/api/v1/admin/atribuicoes",
            json={"usuario_id": str(alvo.user_id), "papel": "DIRETORIA", "escopo_tipo": "global"},
            headers=admin,
        ),
    )
    passo(
        "DELETE /api/v1/admin/atribuicoes/{id_}",
        lambda: cliente.delete(f"/api/v1/admin/atribuicoes/{ctx['atribuicao']}", headers=admin),
    )
    passo(
        "POST /api/v1/admin/mapeamentos-grupo",
        lambda: cliente.post(
            "/api/v1/admin/mapeamentos-grupo",
            json={"grupo_id": str(grupo), "papel": "AUDITOR", "escopo_tipo": "global"},
            headers=admin,
        ),
    )
    passo(
        "DELETE /api/v1/admin/mapeamentos-grupo/{id_}",
        lambda: cliente.delete(
            f"/api/v1/admin/mapeamentos-grupo/{ctx['mapeamento']}", headers=admin
        ),
    )
    app.state.geracao_de_relatorios = geracao_falsa(app.state)
    passo(
        "POST /api/v1/relatorios",
        lambda: cliente.post(
            "/api/v1/relatorios",
            json={"tipo": "inventario_unidades", "formato": "csv"},
            headers=gestor,
        ),
    )
    app.state.diretorio = _DiretorioVazio()
    passo(
        "POST /api/v1/admin/diretorio/sincronizar",
        lambda: cliente.post("/api/v1/admin/diretorio/sincronizar", headers=admin),
    )
    passo(
        "POST /api/v1/auth/login",
        lambda: cliente.post(
            "/api/v1/auth/login",
            json={"username": "cobertura", "password": "senha-errada"},
            headers=agente,
        ),
    )
    passo(
        "POST /api/v1/auth/mfa/confirm",
        lambda: cliente.post(
            "/api/v1/auth/mfa/confirm",
            json={"mfa_token": ctx["desafio"], "code": codigo(ctx["segredo"])},
            headers=agente,
        ),
    )
    passo(
        "POST /api/v1/auth/mfa/verify",
        lambda: cliente.post(
            "/api/v1/auth/mfa/verify",
            json={"mfa_token": ctx["desafio2"], "code": codigo(ctx["segredo"], adiante=1)},
            headers=agente,
        ),
    )
    passo(
        "POST /api/v1/auth/logout",
        lambda: cliente.post(
            "/api/v1/auth/logout",
            headers=agente | {"Authorization": f"Bearer {ctx['acesso']}"},
        ),
    )
    passo(
        "POST /api/v1/auditoria/verificar",
        lambda: cliente.post("/api/v1/auditoria/verificar", json={}, headers=gestor),
    )
    passo(
        "POST /api/v1/unidades/{id}/desativar",
        lambda: cliente.post(
            f"{u}/{ctx['unidade']}/desativar", json={"motivo": "Fim do teste"}, headers=gestor
        ),
    )

    problemas: list[str] = []
    for chave, chamada in chamadas:
        if chave == "POST /api/v1/auth/mfa/confirm":
            ctx["desafio"] = (await login(cliente, "cobertura")).json()["mfa_token"]
            enroll = await cliente.post(
                "/api/v1/auth/mfa/enroll", json={"mfa_token": ctx["desafio"]}
            )
            ctx["segredo"] = segredo_da_uri(enroll.json()["otpauth_uri"])
        if chave == "POST /api/v1/auth/mfa/verify":
            ctx["desafio2"] = (await login(cliente, "cobertura")).json()["mfa_token"]
        antes = await _ultimo_id(sessoes)
        resposta = await chamada()
        if resposta.status_code >= 400 and chave != "POST /api/v1/auth/login":
            problemas.append(f"{chave}: HTTP {resposta.status_code} {resposta.text[:200]}")
            continue
        _guardar_ids(chave, resposta, ctx)
        esperado = MAPA[chave]
        eventos = [e for e in await _eventos_depois(sessoes, antes) if e["action"] == esperado.acao]
        if len(eventos) != 1:
            problemas.append(f"{chave}: {len(eventos)} eventos {esperado.acao}")
            continue
        [evento] = eventos
        obtido = (
            evento["actor_type"],
            evento["origin"],
            evento["result"],
            evento["entity_type"],
            evento["ip"],
            evento["user_agent"],
        )
        desejado = ("usuario", "api", esperado.resultado, esperado.entidade, "127.0.0.1", AGENTE)
        if obtido != desejado:
            problemas.append(f"{chave}: {obtido} != {desejado}")

    assert {chave for chave, _ in chamadas} == MAPA.keys()
    assert problemas == []


def _guardar_ids(chave: str, resposta: httpx.Response, ctx: dict[str, Any]) -> None:
    corpo = resposta.json() if resposta.content else {}
    destino = {
        "POST /api/v1/unidades": "unidade",
        "POST /api/v1/unidades/{id}/equipamentos": "equipamento",
        "POST /api/v1/unidades/{id}/servicos": "servico",
        "POST /api/v1/equipamentos": "solto",
        "POST /api/v1/servicos": "servico_solto",
        "POST /api/v1/referencias/{tipo}": "referencia",
        "POST /api/v1/admin/atribuicoes": "atribuicao",
        "POST /api/v1/admin/mapeamentos-grupo": "mapeamento",
    }.get(chave)
    if destino is not None:
        ctx[destino] = corpo["id"]
    if chave == "POST /api/v1/auth/mfa/verify":
        ctx["acesso"] = corpo["access_token"]


async def test_operacao_nao_gera_fato_duplicado(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """013/R7.6: uma alteração gera um evento na trilha e uma linha no log do banco, sem repetir
    o fato na trilha; um PATCH sem mudança não gera nada em nenhum dos dois."""
    gestor = bearer(app, await logado(sessoes, ("GESTOR_DADOS", GLOBAL)))
    criada = await cliente.post(
        "/api/v1/unidades",
        json={
            "nome": "CAPS Único",
            "tipo_unidade_id": await id_pelo_codigo(sessoes, "tipo_unidade", "CAPS_II"),
            "distrito_id": await id_pelo_codigo(sessoes, "distrito", "DS-I"),
            "cep": "50010100",
            "endereco": "Rua do Sol, 150",
            "status": "ativa",
        },
        headers=gestor,
    )
    url = f"/api/v1/unidades/{criada.json()['id']}"
    antes = await _ultimo_id(sessoes)
    async with sessoes() as sessao:
        log_antes = int(await sessao.scalar(text("SELECT count(*) FROM db_change_log")) or 0)

    alterada = await cliente.patch(
        url, json={"bairro": "Derby"}, headers=gestor | {"If-Match": '"1"'}
    )
    igual = await cliente.patch(url, json={"bairro": "Derby"}, headers=gestor | {"If-Match": '"2"'})

    assert (alterada.status_code, igual.status_code) == (200, 200)
    assert [e["action"] for e in await _eventos_depois(sessoes, antes)] == ["unidade.atualizada"]
    async with sessoes() as sessao:
        linhas = (
            await sessao.execute(
                text("SELECT operation FROM db_change_log ORDER BY id OFFSET :n"), {"n": log_antes}
            )
        ).all()
    assert [linha.operation for linha in linhas] == ["UPDATE"]
