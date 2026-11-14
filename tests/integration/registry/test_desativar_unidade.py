"""`POST /api/v1/unidades/{id}/desativar`: desativar unidade com motivo, sem apagar (006/T6).

Design da 006 § Rotas e § Desativação; matriz da arquitetura-conceitual.md § 4:
`unidade:deactivate` só para `GESTOR_DADOS`, e só global, então não há "fora do escopo" a
testar: quem não é Gestor de Dados recebe 403 mesmo com escopo sobre a unidade. O procedimento
do banco, o 404 e a unidade já inativa estão em `test_desativar.py` (011/T16).
"""

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.main import create_app
from tests.factories import make_settings
from tests.integration.acesso import (
    GLOBAL,
    Atribuicao,
    Sessoes,
    bearer,
    eventos,
    id_pelo_codigo,
    logado,
)
from tests.integration.postgres import BancoDeTeste, motor
from tests.integration.registry.cadastro import inserir_servico, inserir_unidade

ROTA = "/api/v1/unidades/{id}/desativar"


def _rota(unidade: UUID) -> str:
    return ROTA.format(id=unidade)


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
    """Sessões com o login da API (papel sgs_app), para preparar e conferir os dados."""
    engine = motor(banco.url_api)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def _unidade(sessoes: Sessoes, status: str = "ativa") -> UUID:
    """CAPS II (Saúde Mental) no DS I, com o status dado."""
    async with sessoes() as sessao, sessao.begin():
        unidade = await inserir_unidade(await sessao.connection(), "CAPS Galdino Loreto")
        await sessao.execute(
            text("UPDATE health_units SET status = :status WHERE id = :id"),
            {"status": status, "id": unidade},
        )
    return unidade


async def _gravada(sessoes: Sessoes, unidade: UUID) -> dict[str, Any] | None:
    """A unidade como está no banco, ou `None` se a linha não existe."""
    async with sessoes() as sessao:
        resultado = await sessao.execute(
            text("SELECT name, status, version FROM health_units WHERE id = :id"), {"id": unidade}
        )
        linha = resultado.mappings().one_or_none()
    return None if linha is None else dict(linha)


async def test_gestor_de_dados_desativa_unidade_com_motivo_e_auditoria(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """006/R4.1: o status passa a `inativa`, também de `em_implantacao`, e a desativação é
    auditada com o status de antes e o motivo."""
    gestor = await logado(sessoes, ("GESTOR_DADOS", GLOBAL))
    unidade = await _unidade(sessoes, status="em_implantacao")

    resposta = await cliente.post(
        _rota(unidade), json={"motivo": "  Implantação cancelada.  "}, headers=bearer(app, gestor)
    )

    assert resposta.status_code == 200
    assert resposta.json()["status"] == "inativa"
    assert resposta.json()["nome"] == "CAPS Galdino Loreto"
    [evento] = await eventos(sessoes, "unidade.desativada")
    assert evento["changes"] == [{"campo": "status", "de": "em_implantacao", "para": "inativa"}]
    assert evento["metadata"] == {"motivo": "Implantação cancelada."}


async def test_desativacao_nao_apaga_a_unidade_nem_o_que_esta_ligado_a_ela(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """006/R4.2: a linha continua no banco, inativa, e o serviço continua ligado a ela."""
    gestor = await logado(sessoes, ("GESTOR_DADOS", GLOBAL))
    unidade = await _unidade(sessoes)
    async with sessoes() as sessao, sessao.begin():
        servico = await inserir_servico(await sessao.connection(), unidade)

    resposta = await cliente.post(
        _rota(unidade), json={"motivo": "Fechada."}, headers=bearer(app, gestor)
    )

    assert resposta.status_code == 200
    assert await _gravada(sessoes, unidade) == {
        "name": "CAPS Galdino Loreto",
        "status": "inativa",
        "version": 2,
    }
    async with sessoes() as sessao:
        ligada = await sessao.scalar(
            text("SELECT unit_id FROM services WHERE id = :id"), {"id": servico}
        )
    assert ligada == unidade


async def test_sem_bearer_responde_401(cliente: httpx.AsyncClient, sessoes: Sessoes) -> None:
    """003/R4.1: a rota exige autenticação; nada muda."""
    unidade = await _unidade(sessoes)

    resposta = await cliente.post(_rota(unidade), json={"motivo": "Fechada."})

    assert resposta.status_code == 401
    assert resposta.headers["www-authenticate"] == "Bearer"
    assert await _gravada(sessoes, unidade) == {
        "name": "CAPS Galdino Loreto",
        "status": "ativa",
        "version": 1,
    }


async def _atribuicao(sessoes: Sessoes, papel: str, unidade: UUID) -> Atribuicao:
    """O papel com o escopo mais próximo da unidade (CAPS II é Saúde Mental, no DS I)."""
    escopos = {
        "COORD_TECNICO": ("area", str(await id_pelo_codigo(sessoes, "area", "SAUDE_MENTAL"))),
        "TECNICO_DISTRITAL": ("distrito", str(await id_pelo_codigo(sessoes, "distrito", "DS-I"))),
        "GESTOR_UNIDADE": ("unidade", str(unidade)),
    }
    return papel, escopos.get(papel, GLOBAL)


@pytest.mark.parametrize(
    "papel",
    ["COORD_TECNICO", "TECNICO_DISTRITAL", "GESTOR_UNIDADE", "DIRETORIA", "AUDITOR", "ADMIN_TI"],
)
async def test_papel_sem_unidade_deactivate_responde_403_e_nada_muda(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes, papel: str
) -> None:
    """006/R4.1, 003/R4.2, 003/R4.6: só o `GESTOR_DADOS` desativa, mesmo que o papel tenha
    escopo sobre a unidade; o 403 é auditado como `acesso.negado` com a unidade."""
    unidade = await _unidade(sessoes)
    usuario = await logado(sessoes, await _atribuicao(sessoes, papel, unidade))

    resposta = await cliente.post(
        _rota(unidade), json={"motivo": "Fechada."}, headers=bearer(app, usuario)
    )

    assert resposta.status_code == 403
    assert resposta.json()["title"] == "Acesso negado"
    assert await eventos(sessoes, "acesso.negado") == [
        {
            "actor_user_id": usuario.user_id,
            "session_id": usuario.id,
            "entity_type": "unidade",
            "entity_id": str(unidade),
            "changes": [],
            "metadata": {"permissao": "unidade:deactivate", "rota": f"POST {ROTA}"},
        }
    ]
    assert await eventos(sessoes, "unidade.desativada") == []
    assert (await _gravada(sessoes, unidade) or {}).get("status") == "ativa"


@pytest.mark.parametrize(
    ("corpo", "campo"),
    [
        ({}, "motivo"),
        ({"motivo": ""}, "motivo"),
        ({"motivo": "   "}, "motivo"),
        ({"motivo": "x" * 501}, "motivo"),
        ({"motivo": 7}, "motivo"),
        ({"motivo": "Fechada.", "status": "ativa"}, "status"),
    ],
    ids=[
        "sem-motivo",
        "motivo-vazio",
        "motivo-em-branco",
        "motivo-longo",
        "motivo-numero",
        "extra",
    ],
)
async def test_motivo_ausente_ou_invalido_responde_422_e_nada_muda(
    app: FastAPI,
    cliente: httpx.AsyncClient,
    sessoes: Sessoes,
    corpo: dict[str, Any],
    campo: str,
) -> None:
    """006/R4.1: a desativação exige motivo (até 500 caracteres); campo a mais é recusado."""
    gestor = await logado(sessoes, ("GESTOR_DADOS", GLOBAL))
    unidade = await _unidade(sessoes)

    resposta = await cliente.post(_rota(unidade), json=corpo, headers=bearer(app, gestor))

    assert resposta.status_code == 422
    assert [erro["campo"] for erro in resposta.json()["errors"]] == [campo]
    assert await eventos(sessoes, "unidade.desativada") == []
    assert (await _gravada(sessoes, unidade) or {}).get("status") == "ativa"
