"""Versão invalidada por alteração fora da API (011/T17, com a 006/T5).

O caso de uso da 006 não incrementa a versão: compara o `If-Match` com a que o banco tem, e o
`UPDATE ... WHERE version = :esperada` só grava se ninguém passou na frente. Quem incrementa é o
trigger `trg_health_units_version` (011/T5), em toda escrita, inclusive a feita direto no banco.
"""

from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.main import create_app
from tests.factories import make_settings
from tests.integration.acesso import GLOBAL, Sessoes, bearer, eventos, id_pelo_codigo, logado
from tests.integration.postgres import BancoDeTeste, motor


@pytest.fixture
async def app(banco: BancoDeTeste) -> AsyncIterator[FastAPI]:
    app = create_app(make_settings(database_url=SecretStr(banco.url_api)))
    yield app
    await app.state.engine.dispose()


@pytest.fixture
async def sessoes(banco: BancoDeTeste) -> AsyncIterator[Sessoes]:
    engine = motor(banco.url_api)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def test_patch_com_etag_anterior_a_update_direto_no_banco_responde_412(
    app: FastAPI, banco: BancoDeTeste, sessoes: Sessoes
) -> None:
    """011/R8.3, 006/R3.2: o superusuário altera a unidade direto no banco; o `PATCH` com o
    `ETag` lido antes responde 412 e não sobrescreve a alteração."""
    gestor = await logado(sessoes, ("GESTOR_DADOS", GLOBAL))
    transporte = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transporte, base_url="http://teste") as cliente:
        criada = await cliente.post(
            "/api/v1/unidades",
            json={
                "nome": "CAPS Galdino Loreto",
                "tipo_unidade_id": await id_pelo_codigo(sessoes, "tipo_unidade", "CAPS_II"),
                "distrito_id": await id_pelo_codigo(sessoes, "distrito", "DS-I"),
                "cep": "50010-100",
                "endereco": "Rua do Sol, 150",
                "status": "ativa",
            },
            headers=bearer(app, gestor),
        )
        # A versão "em mãos": o ETag da unidade recém-criada.
        unidade, etag = criada.json()["id"], criada.headers["etag"]

        dono = motor(banco.url_dono)
        async with dono.begin() as conexao:
            await conexao.execute(
                text("UPDATE health_units SET phone = '8133550000' WHERE id = :id"),
                {"id": unidade},
            )
        await dono.dispose()

        resposta = await cliente.patch(
            f"/api/v1/unidades/{unidade}",
            json={"telefone": "8133551234"},
            headers={**bearer(app, gestor), "If-Match": etag},
        )

    assert (etag, resposta.status_code) == ('"1"', 412)
    async with sessoes() as sessao:
        telefone, versao = (
            await sessao.execute(
                text("SELECT phone, version FROM health_units WHERE id = :id"), {"id": unidade}
            )
        ).one()
    assert (telefone, versao) == ("8133550000", 2)
    assert await eventos(sessoes, "unidade.atualizada") == []
