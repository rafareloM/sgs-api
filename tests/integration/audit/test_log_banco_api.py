"""Log do banco pela API: `GET /api/v1/auditoria/banco` (spec 011, R7.7 e R7.8; design § Rotas).

O cadastro e os registros do log entram direto no banco, pelo dono (superusuário): o trigger grava
o log das alterações do cadastro, e os registros com data escolhida, para os filtros por período,
são inseridos no log pelo próprio dono. A leitura é sempre pela API, com o login dela.
"""

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import make_url, text
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker

from src.main import create_app
from tests.factories import make_settings
from tests.integration.acesso import GLOBAL, Sessoes, bearer, eventos, id_pelo_codigo, logado
from tests.integration.postgres import BancoDeTeste, motor
from tests.integration.registry.cadastro import inserir_unidade

LOG = "/api/v1/auditoria/banco"


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


@pytest.fixture
async def dono(banco: BancoDeTeste) -> AsyncIterator[AsyncConnection]:
    """Conexão do dono do banco (superusuário), para semear o cadastro e o log. O teste confirma
    com `commit()` antes de chamar a API."""
    engine = motor(banco.url_dono)
    async with engine.connect() as conexao:
        yield conexao
    await engine.dispose()


async def _listar(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes, **params: Any
) -> dict[str, Any]:
    """A resposta da listagem para um auditor com `auditoria:read` global."""
    auditor = await logado(sessoes, ("AUDITOR", GLOBAL))
    resposta = await cliente.get(LOG, params=params, headers=bearer(app, auditor))
    assert resposta.status_code == 200, resposta.text
    corpo: dict[str, Any] = resposta.json()
    return corpo


async def test_lista_as_alteracoes_do_cadastro_da_mais_recente_para_a_mais_antiga(
    app: FastAPI,
    cliente: httpx.AsyncClient,
    sessoes: Sessoes,
    dono: AsyncConnection,
    banco: BancoDeTeste,
) -> None:
    """011/R7.7: cada registro do log com data e hora, tabela, operação, linha, colunas alteradas
    (de/para), usuário de banco e origem; o mais recente primeiro. A alteração pelo superusuário
    vem como fora da API (R7.2)."""
    unidade = await inserir_unidade(dono, "CAPS Espaço Azul")
    await dono.commit()
    await dono.execute(
        text("UPDATE health_units SET phone = '8133551234' WHERE id = :id"), {"id": unidade}
    )
    await dono.commit()

    corpo = await _listar(app, cliente, sessoes)

    assert corpo["total"] == 2
    assert (corpo["pagina"], corpo["tamanho"]) == (1, 20)
    alteracao, inclusao = corpo["itens"]
    superusuario = make_url(banco.url_dono).username
    assert {chave: valor for chave, valor in alteracao.items() if chave != "ocorrido_em"} == {
        "tabela": "health_units",
        "operacao": "UPDATE",
        "linha_id": str(unidade),
        "colunas_alteradas": {"phone": {"de": None, "para": "8133551234"}},
        "usuario_banco": superusuario,
        "via_api": False,
    }
    assert (inclusao["tabela"], inclusao["operacao"]) == ("health_units", "INSERT")
    assert inclusao["colunas_alteradas"]["name"] == {"de": None, "para": "CAPS Espaço Azul"}
    assert datetime.fromisoformat(alteracao["ocorrido_em"]) > datetime.fromisoformat(
        inclusao["ocorrido_em"]
    )
    assert datetime.fromisoformat(alteracao["ocorrido_em"]).utcoffset() is not None


async def _registrar(
    dono: AsyncConnection,
    ocorrido_em: str,
    *,
    tabela: str = "health_units",
    via_api: bool = False,
) -> UUID:
    """Um registro do log com data e hora, tabela e origem escolhidas; devolve o `row_id`."""
    linha = uuid4()
    await dono.execute(
        text(
            "INSERT INTO db_change_log"
            " (occurred_at, table_name, operation, row_id, changed_columns, db_user, via_api, txid)"
            " VALUES (:ocorrido_em, :tabela, 'UPDATE', :linha,"
            " CAST('{}' AS jsonb), 'sgs', :via_api, txid_current())"
        ),
        {
            "ocorrido_em": datetime.fromisoformat(ocorrido_em),
            "tabela": tabela,
            "linha": linha,
            "via_api": via_api,
        },
    )
    return linha


def _linhas(corpo: dict[str, Any]) -> list[str]:
    return [item["linha_id"] for item in corpo["itens"]]


async def test_filtra_por_periodo_com_as_duas_pontas_incluidas(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes, dono: AsyncConnection
) -> None:
    """011/R7.7: `de` e `ate` restringem a data e hora do registro, com as pontas incluídas."""
    janeiro = await _registrar(dono, "2026-01-15T12:00:00+00:00")
    fevereiro = await _registrar(dono, "2026-02-15T12:00:00+00:00")
    marco = await _registrar(dono, "2026-03-15T12:00:00+00:00")
    await dono.commit()

    so_fevereiro = await _listar(
        app,
        cliente,
        sessoes,
        de="2026-02-15T12:00:00+00:00",
        ate="2026-02-15T12:00:00+00:00",
    )
    desde_fevereiro = await _listar(app, cliente, sessoes, de="2026-02-01T00:00:00-03:00")
    ate_fevereiro = await _listar(app, cliente, sessoes, ate="2026-02-28T23:59:59-03:00")

    assert (_linhas(so_fevereiro), so_fevereiro["total"]) == ([str(fevereiro)], 1)
    assert _linhas(desde_fevereiro) == [str(marco), str(fevereiro)]
    assert _linhas(ate_fevereiro) == [str(fevereiro), str(janeiro)]


async def test_filtra_por_tabela_e_por_origem(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes, dono: AsyncConnection
) -> None:
    """011/R7.7: `tabela` restringe a tabela do cadastro; `fora_da_api=true` traz só o que não
    veio da API (011/R7.2) e `fora_da_api=false`, só o que veio."""
    unidade_fora = await _registrar(dono, "2026-01-01T10:00:00+00:00", via_api=False)
    unidade_api = await _registrar(dono, "2026-01-01T11:00:00+00:00", via_api=True)
    servico_fora = await _registrar(
        dono, "2026-01-01T12:00:00+00:00", tabela="services", via_api=False
    )
    await dono.commit()

    servicos = await _listar(app, cliente, sessoes, tabela="services")
    fora = await _listar(app, cliente, sessoes, fora_da_api="true")
    pela_api = await _listar(app, cliente, sessoes, fora_da_api="false")
    unidades_fora = await _listar(app, cliente, sessoes, tabela="health_units", fora_da_api=True)

    assert _linhas(servicos) == [str(servico_fora)]
    assert _linhas(fora) == [str(servico_fora), str(unidade_fora)]
    assert _linhas(pela_api) == [str(unidade_api)]
    assert _linhas(unidades_fora) == [str(unidade_fora)]


async def test_pagina_os_registros_com_o_total(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes, dono: AsyncConnection
) -> None:
    """011/R7.7: paginação com o total da consulta inteira."""
    linhas = [await _registrar(dono, f"2026-01-0{dia}T12:00:00+00:00") for dia in range(1, 6)]
    await dono.commit()

    segunda = await _listar(app, cliente, sessoes, pagina=2, tamanho=2)
    depois_da_ultima = await _listar(app, cliente, sessoes, pagina=9, tamanho=2)

    assert (_linhas(segunda), segunda["total"]) == ([str(linhas[2]), str(linhas[1])], 5)
    assert (depois_da_ultima["itens"], depois_da_ultima["total"]) == ([], 5)


@pytest.mark.parametrize(
    "params",
    [
        {"tabela": "users"},
        {"de": "2026-01-01T00:00:00"},
        {"fora_da_api": "talvez"},
        {"tamanho": 0},
    ],
)
async def test_filtro_mal_formado_responde_422(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes, params: dict[str, Any]
) -> None:
    """Design da 011 § Rotas: tabela fora das três do cadastro, data sem fuso, booleano inválido
    ou paginação inválida dão 422."""
    auditor = await logado(sessoes, ("AUDITOR", GLOBAL))

    resposta = await cliente.get(LOG, params=params, headers=bearer(app, auditor))

    assert resposta.status_code == 422, resposta.text


async def test_auditoria_read_fora_do_escopo_global_responde_403_e_audita(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes, dono: AsyncConnection
) -> None:
    """011/R7.8, 003/R4.6: quem tem `auditoria:read` só numa área técnica recebe 403, sem nada
    do log, e a negação fica na trilha."""
    await _registrar(dono, "2026-01-01T12:00:00+00:00")
    await dono.commit()
    area = await id_pelo_codigo(sessoes, "area", "SAUDE_MENTAL")
    coordenador = await logado(sessoes, ("COORD_TECNICO", ("area", str(area))))

    resposta = await cliente.get(LOG, headers=bearer(app, coordenador))

    assert resposta.status_code == 403, resposta.text
    assert resposta.headers["content-type"].startswith("application/problem+json")
    assert "itens" not in resposta.json()
    negados = await eventos(sessoes, "acesso.negado")
    assert [(e["actor_user_id"], e["metadata"]["permissao"]) for e in negados] == [
        (coordenador.user_id, "auditoria:read")
    ]


async def test_sem_auditoria_read_responde_403(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """011/R7.8: sem a permissão, 403."""
    leitor = await logado(sessoes, ("DIRETORIA", GLOBAL))

    resposta = await cliente.get(LOG, headers=bearer(app, leitor))

    assert resposta.status_code == 403


async def test_sem_token_responde_401(cliente: httpx.AsyncClient) -> None:
    """Design da 011 § Rotas: sem access token, 401."""
    resposta = await cliente.get(LOG)

    assert resposta.status_code == 401
