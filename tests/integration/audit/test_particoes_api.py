"""Partições do log do banco pela API: `GET /api/v1/auditoria/banco/particoes` (spec 011, R6.9 e
R7.8; design § Rotas).

As partições mensais são as que a migração cria (`sp_ensure_monthly_partitions`, 011/T8: o mês
atual e os 12 seguintes, em UTC); os registros entram no log pelo dono do banco, com a data
escolhida. Os meses esperados vêm do relógio do Python, em UTC.
"""

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from typing import Any
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker

from src.main import create_app
from tests.factories import make_settings
from tests.integration.acesso import GLOBAL, Sessoes, bearer, id_pelo_codigo, logado
from tests.integration.postgres import BancoDeTeste, motor

PARTICOES = "/api/v1/auditoria/banco/particoes"
MESES_A_FRENTE = 12


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
    """Conexão do dono do banco (superusuário), para semear o log."""
    engine = motor(banco.url_dono)
    async with engine.connect() as conexao:
        yield conexao
    await engine.dispose()


def _mes(deslocamento: int) -> date:
    """Primeiro dia do mês `deslocamento` meses depois do atual, em UTC."""
    hoje = datetime.now(UTC).date()
    indice = hoje.year * 12 + hoje.month - 1 + deslocamento
    return date(indice // 12, indice % 12 + 1, 1)


def _inicio(deslocamento: int) -> datetime:
    mes = _mes(deslocamento)
    return datetime(mes.year, mes.month, 1, tzinfo=UTC)


async def _registrar(dono: AsyncConnection, ocorrido_em: datetime) -> None:
    await dono.execute(
        text(
            "INSERT INTO db_change_log"
            " (occurred_at, table_name, operation, row_id, changed_columns, db_user, via_api, txid)"
            " VALUES (:ocorrido_em, 'health_units', 'UPDATE', :linha, CAST('{}' AS jsonb), 'sgs',"
            " false, txid_current())"
        ),
        {"ocorrido_em": ocorrido_em, "linha": uuid4()},
    )


async def test_lista_cada_particao_com_o_intervalo_e_a_quantidade_de_registros(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes, dono: AsyncConnection
) -> None:
    """011/R6.9: as partições mensais em ordem, com o início incluído e o fim excluído do
    intervalo, e a DEFAULT por último, com o intervalo nulo; cada uma com os seus registros."""
    for _ in range(2):
        await _registrar(dono, _inicio(0))
    await _registrar(dono, _inicio(2))
    await _registrar(dono, datetime(2001, 1, 1, tzinfo=UTC))  # sem partição mensal: DEFAULT
    await dono.commit()
    auditor = await logado(sessoes, ("AUDITOR", GLOBAL))

    resposta = await cliente.get(PARTICOES, headers=bearer(app, auditor))

    assert resposta.status_code == 200, resposta.text
    particoes: list[dict[str, Any]] = resposta.json()
    *mensais, default = particoes
    assert default == {"nome": "db_change_log_default", "de": None, "ate": None, "registros": 1}
    assert [
        (p["nome"], datetime.fromisoformat(p["de"]), datetime.fromisoformat(p["ate"]))
        for p in mensais
    ] == [
        (f"db_change_log_y{_mes(d).year:04d}m{_mes(d).month:02d}", _inicio(d), _inicio(d + 1))
        for d in range(MESES_A_FRENTE + 1)
    ]
    assert [p["registros"] for p in mensais] == [2, 0, 1] + [0] * (MESES_A_FRENTE - 2)


async def test_auditoria_read_fora_do_escopo_global_responde_403(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """011/R7.8 (design § Rotas: `auditoria:read` global): escopo de área dá 403."""
    area = await id_pelo_codigo(sessoes, "area", "SAUDE_MENTAL")
    coordenador = await logado(sessoes, ("COORD_TECNICO", ("area", str(area))))

    resposta = await cliente.get(PARTICOES, headers=bearer(app, coordenador))

    assert resposta.status_code == 403, resposta.text


async def test_sem_token_responde_401(cliente: httpx.AsyncClient) -> None:
    """Design da 011 § Rotas: sem access token, 401."""
    resposta = await cliente.get(PARTICOES)

    assert resposta.status_code == 401
