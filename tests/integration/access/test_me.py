"""`GET /api/v1/me`: perfil do usuário logado (003/T6).

Design da 003 § Rotas (autenticado, sem permissão) e § Resolução de permissões; matriz da
arquitetura-conceitual.md § 4.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.core.ids import uuid7
from src.main import create_app
from tests.factories import make_settings
from tests.integration.acesso import GLOBAL, Sessoes, bearer, id_pelo_codigo, logado
from tests.integration.postgres import BancoDeTeste, motor

ROTA = "/api/v1/me"


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
    engine = motor(banco.url_api)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def test_me_devolve_dados_basicos_papeis_com_escopo_e_permissoes_efetivas(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """003/R5.1: um técnico do DS III que também é gestor de uma unidade vê os dois papéis, cada
    um com o seu escopo, e a união das permissões, cada uma nos escopos em que vale."""
    ds3 = str(await id_pelo_codigo(sessoes, "distrito", "DS-III"))
    unidade = str(uuid7())
    login = await logado(
        sessoes, ("TECNICO_DISTRITAL", ("distrito", ds3)), ("GESTOR_UNIDADE", ("unidade", unidade))
    )

    resposta = await cliente.get(ROTA, headers=bearer(app, login))

    assert resposta.status_code == 200
    perfil = resposta.json()
    assert perfil.keys() == {"id", "username", "nome", "email", "papeis", "permissoes"}
    assert perfil["id"] == str(login.user_id)
    assert perfil["nome"] == "Maria Silva"
    assert perfil["email"] is None
    papeis = {(p["codigo"], p["escopo"]["tipo"], p["escopo"]["id"]) for p in perfil["papeis"]}
    assert papeis == {
        ("TECNICO_DISTRITAL", "distrito", ds3),
        ("GESTOR_UNIDADE", "unidade", unidade),
    }
    assert all(p["nome"] and p["origem"] == "direta" for p in perfil["papeis"])
    permissoes = perfil["permissoes"]
    # `unidade:read` é G nos dois papéis; `unidade:update` é D num e U no outro.
    assert permissoes["unidade:read"] == [{"tipo": "global", "id": None}]
    assert sorted(permissoes["unidade:update"], key=lambda e: e["tipo"]) == [
        {"tipo": "distrito", "id": ds3},
        {"tipo": "unidade", "id": unidade},
    ]
    assert "unidade:create" not in permissoes
    assert "papel:assign" not in permissoes


async def test_me_nao_expoe_segredo(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """003/R5.1 e steering/security.md: nada de hash de senha, token ou id externo na resposta."""
    login = await logado(sessoes, ("GESTOR_DADOS", GLOBAL))

    resposta = await cliente.get(ROTA, headers=bearer(app, login))

    assert resposta.status_code == 200
    corpo = resposta.text.lower()
    for proibido in ("password", "senha", "hash", "token", "external", "argon2"):
        assert proibido not in corpo


async def test_me_omite_atribuicao_expirada(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """003/R5.1 com R2.3: papel com validade vencida não aparece nem dá permissão."""
    login = await logado(sessoes)
    async with sessoes() as sessao, sessao.begin():
        await sessao.execute(
            text(
                "INSERT INTO role_assignments"
                " (id, user_id, role_id, scope_type, scope_id, origin, valid_until)"
                " SELECT :id, :usuario, id, 'global', NULL, 'direct', :ate"
                " FROM roles WHERE code = 'GESTOR_DADOS'"
            ),
            {"id": uuid7(), "usuario": login.user_id, "ate": datetime.now(UTC) - timedelta(days=1)},
        )

    resposta = await cliente.get(ROTA, headers=bearer(app, login))

    assert resposta.status_code == 200
    assert resposta.json()["papeis"] == []
    assert resposta.json()["permissoes"] == {}


async def test_me_sem_token_responde_401(cliente: httpx.AsyncClient) -> None:
    """Design da 003 § Rotas: `GET /me` exige autenticação."""
    resposta = await cliente.get(ROTA)

    assert resposta.status_code == 401
