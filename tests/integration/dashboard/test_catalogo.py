"""Catálogo de consultas pela API (spec 011, R3.1 e R3.2; design § Rotas).

O catálogo é uma lista fixa, uma entrada por rota de leitura da 011 (as quatro consultas, o
inventário, o histórico da unidade, o log do banco e as partições). Cada usuário vê só as
entradas que pode executar com as permissões efetivas dele (spec 003).
"""

from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.main import create_app
from tests.factories import make_settings
from tests.integration.acesso import GLOBAL, Sessoes, bearer, id_pelo_codigo, logado
from tests.integration.postgres import BancoDeTeste, motor

CATALOGO = "/api/v1/dashboard/consultas"

CAMPOS = {
    "slug",
    "titulo",
    "justificativa",
    "rota",
    "parametros",
    "colunas",
    "permissao",
    "grafico_sugerido",
}

# As rotas de leitura da 011 (design § Rotas), com a permissão de cada uma.
ROTAS_DO_DASHBOARD = {
    "/api/v1/dashboard/consultas/unidades-sem-servico",
    "/api/v1/dashboard/consultas/conciliacao-unidade-equipamento",
    "/api/v1/dashboard/consultas/distritos-cnes-acima-da-media",
    "/api/v1/dashboard/consultas/unidades-servico-fora-cnes",
    "/api/v1/dashboard/consultas/inventario",
}
HISTORICO = "/api/v1/unidades/{id}/historico"
LOG = "/api/v1/auditoria/banco"
PARTICOES = "/api/v1/auditoria/banco/particoes"


@pytest.fixture
async def app(banco: BancoDeTeste) -> AsyncIterator[FastAPI]:
    app = create_app(make_settings(database_url=SecretStr(banco.url_api)))
    yield app
    await app.state.engine.dispose()


@pytest.fixture
async def cliente(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transporte = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transporte, base_url="http://teste") as cliente:
        yield cliente


@pytest.fixture
async def sessoes(banco: BancoDeTeste) -> AsyncIterator[Sessoes]:
    """Sessões com o login da API (papel sgs_app), para criar usuários e atribuições."""
    engine = motor(banco.url_api)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def test_cada_entrada_descreve_a_consulta(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """011/R3.1: com `dashboard:read` e `auditoria:read` globais, o catálogo lista as oito rotas
    de leitura, cada uma com título, justificativa, parâmetros, colunas, permissão e gráfico."""
    gestor = await logado(sessoes, ("GESTOR_DADOS", GLOBAL))

    resposta = await cliente.get(CATALOGO, headers=bearer(app, gestor))

    assert resposta.status_code == 200
    entradas = resposta.json()
    rotas = {entrada["rota"]: entrada for entrada in entradas}
    assert set(rotas) == ROTAS_DO_DASHBOARD | {HISTORICO, LOG, PARTICOES}
    assert set(rotas) <= set(app.openapi()["paths"])
    assert len({entrada["slug"] for entrada in entradas}) == len(entradas)
    for entrada in entradas:
        assert set(entrada) == CAMPOS
        assert all(entrada[campo] for campo in ("titulo", "justificativa", "grafico_sugerido"))
        assert entrada["colunas"], entrada["slug"]
        for coluna in entrada["colunas"]:
            assert set(coluna) == {"nome", "descricao"}
            assert all(coluna.values())
        for parametro in entrada["parametros"]:
            assert set(parametro) == {"nome", "descricao", "obrigatorio"}
            assert parametro["nome"]
            assert parametro["descricao"]
            assert isinstance(parametro["obrigatorio"], bool)
    for rota in ROTAS_DO_DASHBOARD:
        assert rotas[rota]["permissao"] == "dashboard:read"
    for rota in (HISTORICO, LOG, PARTICOES):
        assert rotas[rota]["permissao"] == "auditoria:read"
    inventario = rotas["/api/v1/dashboard/consultas/inventario"]
    assert {p["nome"] for p in inventario["parametros"]} == {
        "distrito",
        "tipo",
        "pagina",
        "tamanho",
    }
    assert "situacao_cadastral" in {c["nome"] for c in inventario["colunas"]}
    assert rotas[PARTICOES]["parametros"] == []


async def test_sem_auditoria_read_historico_log_e_particoes_nao_aparecem(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """011/R3.2: a Diretoria tem `dashboard:read`, mas não `auditoria:read`: vê só as consultas
    do dashboard."""
    diretoria = await logado(sessoes, ("DIRETORIA", GLOBAL))

    resposta = await cliente.get(CATALOGO, headers=bearer(app, diretoria))

    assert resposta.status_code == 200
    assert {entrada["rota"] for entrada in resposta.json()} == ROTAS_DO_DASHBOARD


async def test_auditoria_read_de_distrito_ve_o_historico_mas_nao_o_log(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """011/R3.2, R7.8: o log e as partições exigem `auditoria:read` global; com ela só no
    distrito, o técnico pode ler o histórico das unidades do distrito, mas não o log."""
    ds3 = await id_pelo_codigo(sessoes, "distrito", "DS-III")
    tecnico = await logado(sessoes, ("TECNICO_DISTRITAL", ("distrito", str(ds3))))

    resposta = await cliente.get(CATALOGO, headers=bearer(app, tecnico))

    assert resposta.status_code == 200
    assert {entrada["rota"] for entrada in resposta.json()} == ROTAS_DO_DASHBOARD | {HISTORICO}


async def test_sem_dashboard_read_da_403(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """011/R3.1: o catálogo exige `dashboard:read`; o Auditor, que não a tem, recebe 403."""
    auditor = await logado(sessoes, ("AUDITOR", GLOBAL))

    resposta = await cliente.get(CATALOGO, headers=bearer(app, auditor))

    assert resposta.status_code == 403


async def test_sem_token_da_401(cliente: httpx.AsyncClient) -> None:
    """011/R3.1: sem access token, 401."""
    assert (await cliente.get(CATALOGO)).status_code == 401
