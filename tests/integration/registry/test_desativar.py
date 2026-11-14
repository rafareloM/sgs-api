"""`POST /api/v1/unidades/{id}/desativar` pelo procedimento `sp_deactivate_unit` (011/T16).

Design da 011 § Fluxo, Desativação: o caso de uso da 006 chama o procedimento, traduz o SQLSTATE
`SGS01` em 404 com detalhe fixo e audita `unidade.desativada` só quando o status muda. Matriz da
arquitetura-conceitual.md § 4: `unidade:deactivate` só para `GESTOR_DADOS`, global.
"""

import asyncio
from collections.abc import AsyncIterator
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.core.errors import NotFound
from src.core.ids import uuid7
from src.main import create_app
from src.modules.audit.application.registrar import Ator
from src.modules.registry.application.unidades import desativar_unidade
from tests.factories import make_settings
from tests.integration.acesso import GLOBAL, Sessoes, bearer, eventos, logado
from tests.integration.postgres import BancoDeTeste, motor
from tests.integration.registry.cadastro import inserir_unidade


def _rota(unidade: UUID | str) -> str:
    return f"/api/v1/unidades/{unidade}/desativar"


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


async def _unidade_ativa(sessoes: Sessoes, nome: str = "CAPS Galdino Loreto") -> UUID:
    async with sessoes() as sessao, sessao.begin():
        return await inserir_unidade(await sessao.connection(), nome)


async def test_desativacao_responde_200_com_a_unidade_e_audita_o_motivo(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """011/R6.1, 011/R6.2: a unidade volta inativa, com a versão nova do procedimento no `ETag`,
    e `unidade.desativada` leva o status de antes e o motivo."""
    gestor = await logado(sessoes, ("GESTOR_DADOS", GLOBAL))
    unidade = await _unidade_ativa(sessoes)

    resposta = await cliente.post(
        _rota(unidade),
        json={"motivo": "Unidade fechada pela Secretaria."},
        headers=bearer(app, gestor),
    )

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert (corpo["id"], corpo["status"], corpo["versao"]) == (str(unidade), "inativa", 2)
    assert resposta.headers["etag"] == '"2"'
    assert await eventos(sessoes, "unidade.desativada") == [
        {
            "actor_user_id": gestor.user_id,
            "session_id": gestor.id,
            "entity_type": "unidade",
            "entity_id": str(unidade),
            "changes": [{"campo": "status", "de": "ativa", "para": "inativa"}],
            "metadata": {"motivo": "Unidade fechada pela Secretaria."},
        }
    ]


async def test_unidade_ja_inativa_responde_200_sem_alterar_nada_e_sem_auditoria(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """011/R6.4: a segunda desativação devolve a unidade como estava, com o mesmo `ETag`."""
    gestor = await logado(sessoes, ("GESTOR_DADOS", GLOBAL))
    unidade = await _unidade_ativa(sessoes)
    primeira = await cliente.post(
        _rota(unidade), json={"motivo": "Fechada."}, headers=bearer(app, gestor)
    )

    segunda = await cliente.post(
        _rota(unidade), json={"motivo": "Fechada de novo."}, headers=bearer(app, gestor)
    )

    assert segunda.status_code == 200
    assert segunda.json() == primeira.json()
    assert segunda.headers["etag"] == primeira.headers["etag"] == '"2"'
    desativacoes = await eventos(sessoes, "unidade.desativada")
    assert [evento["metadata"] for evento in desativacoes] == [{"motivo": "Fechada."}]


async def test_desativacoes_simultaneas_auditam_uma_vez(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """011/R6.4: a segunda espera a primeira e já encontra a unidade inativa."""
    gestor = await logado(sessoes, ("GESTOR_DADOS", GLOBAL))
    unidade = await _unidade_ativa(sessoes)

    respostas = await asyncio.gather(
        *(
            cliente.post(_rota(unidade), json={"motivo": "Fechada."}, headers=bearer(app, gestor))
            for _ in range(2)
        )
    )

    assert [resposta.status_code for resposta in respostas] == [200, 200]
    assert {resposta.json()["versao"] for resposta in respostas} == {2}
    assert len(await eventos(sessoes, "unidade.desativada")) == 1


@pytest.mark.parametrize("unidade", [uuid7(), "nao-e-uuid"], ids=["inexistente", "id-invalido"])
async def test_unidade_inexistente_responde_404_sem_a_mensagem_do_banco(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes, unidade: UUID | str
) -> None:
    """011/R6.3: o 404 tem detalhe fixo; nada do banco (SQLSTATE, mensagem, id) chega ao cliente."""
    gestor = await logado(sessoes, ("GESTOR_DADOS", GLOBAL))

    resposta = await cliente.post(
        _rota(unidade), json={"motivo": "Duplicada."}, headers=bearer(app, gestor)
    )

    assert resposta.status_code == 404
    assert resposta.headers["content-type"] == "application/problem+json"
    problema = resposta.json()
    assert (problema["title"], problema["detail"]) == (
        "Recurso não encontrado",
        "O recurso pedido não existe.",
    )
    assert "SGS01" not in resposta.text
    assert str(unidade) not in resposta.text
    assert await eventos(sessoes, "unidade.desativada") == []


async def test_sqlstate_do_procedimento_vira_not_found_com_detalhe_fixo(
    app: FastAPI, sessoes: Sessoes
) -> None:
    """011/R6.3: o `SGS01` do procedimento vira `NotFound` sem a mensagem do `RAISE`.

    Pela rota, o `require` já responde 404 para unidade inexistente antes de chamar o caso de
    uso; aqui o caso de uso chama o procedimento com uma unidade que não existe, como numa
    corrida entre a verificação e o CALL.
    """
    unidade = uuid7()
    estado = app.state
    async with sessoes() as sessao:
        with pytest.raises(NotFound) as erro:
            async with sessao.begin():
                await desativar_unidade(
                    unidade,
                    motivo="Duplicada.",
                    ator=Ator(),
                    unidades=estado.repositorio_de_unidades(sessao),
                    auditoria=estado.auditoria(sessao),
                )

    assert erro.value.detail == "O recurso pedido não existe."
    assert erro.value.extensoes == {}
    assert await eventos(sessoes, "unidade.desativada") == []
