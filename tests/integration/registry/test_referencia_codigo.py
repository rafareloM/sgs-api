"""`PATCH /api/v1/referencias/tipos-equipamento/{id}` corrigindo o código (011/T18, com 006/T9).

O equipamento aponta o tipo pelo código, com `ON UPDATE CASCADE` (0006): corrigir o código do
tipo leva o código novo a todos os equipamentos dele, e a correção é auditada como
`referencia.atualizada` com a quantidade de equipamentos afetados (011/R9.2, 006/R7.3).
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
from tests.integration.acesso import GLOBAL, Sessoes, bearer, eventos, logado
from tests.integration.postgres import BancoDeTeste, motor
from tests.integration.registry.cadastro import inserir_equipamento, inserir_unidade

ROTA = "/api/v1/referencias/tipos-equipamento/{id}"


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


async def _tipo(sessoes: Sessoes, codigo: str) -> int:
    async with sessoes() as sessao:
        id_ = await sessao.scalar(
            text("SELECT id FROM equipment_types WHERE code = :codigo"), {"codigo": codigo}
        )
    assert id_ is not None
    return int(id_)


async def _codigos_dos_equipamentos(sessoes: Sessoes) -> list[str]:
    async with sessoes() as sessao:
        resultado = await sessao.scalars(
            text("SELECT equipment_type_code FROM equipments ORDER BY equipment_type_code")
        )
        return list(resultado)


async def _equipamentos(sessoes: Sessoes) -> None:
    """Duas maternidades (uma sem unidade) e uma policlínica."""
    async with sessoes() as sessao, sessao.begin():
        conexao = await sessao.connection()
        unidade = await inserir_unidade(conexao, "CAPS Galdino Loreto")
        await inserir_equipamento(conexao, unidade, nome="Maternidade Bandeira Filho")
        await inserir_equipamento(conexao, None, nome="Maternidade Barros Lima")
        await inserir_equipamento(conexao, unidade, nome="Policlínica Lessa", tipo="POLICLINICA")


async def test_corrigir_codigo_leva_o_codigo_novo_aos_equipamentos_e_audita_a_quantidade(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """011/R9.2, 006/R7.3: os equipamentos do tipo passam a usar o código novo; os de outro tipo
    não mudam; `referencia.atualizada` traz o de/para do código e `equipamentos_afetados`."""
    gestor = await logado(sessoes, ("GESTOR_DADOS", GLOBAL))
    await _equipamentos(sessoes)
    tipo = await _tipo(sessoes, "MATERNIDADE")

    resposta = await cliente.patch(
        ROTA.format(id=tipo), json={"codigo": "MATERNIDADE_MUN"}, headers=bearer(app, gestor)
    )

    assert resposta.status_code == 200
    assert resposta.json() == {
        "id": tipo,
        "codigo": "MATERNIDADE_MUN",
        "nome": "Maternidade",
        "ativo": True,
    }
    assert await _codigos_dos_equipamentos(sessoes) == [
        "MATERNIDADE_MUN",
        "MATERNIDADE_MUN",
        "POLICLINICA",
    ]
    [evento] = await eventos(sessoes, "referencia.atualizada")
    assert evento["actor_user_id"] == gestor.user_id
    assert evento["entity_type"] == "tipo_equipamento"
    assert evento["entity_id"] == str(tipo)
    assert evento["changes"] == [
        {"campo": "codigo", "de": "MATERNIDADE", "para": "MATERNIDADE_MUN"}
    ]
    assert evento["metadata"] == {"equipamentos_afetados": 2}


async def test_tipo_sem_equipamento_audita_zero_afetados(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """011/R9.2: a quantidade é auditada também quando nenhum equipamento usa o tipo."""
    gestor = await logado(sessoes, ("GESTOR_DADOS", GLOBAL))
    tipo = await _tipo(sessoes, "UTI_MOVEL")

    resposta = await cliente.patch(
        ROTA.format(id=tipo), json={"codigo": "SAMU_USA"}, headers=bearer(app, gestor)
    )

    assert resposta.status_code == 200
    [evento] = await eventos(sessoes, "referencia.atualizada")
    assert evento["metadata"] == {"equipamentos_afetados": 0}


async def test_codigo_repetido_responde_409_e_nada_muda(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """011/R9.2 (design § Rotas: 409 com código repetido): o código é único; nem o tipo nem os
    equipamentos mudam, e nada é auditado."""
    gestor = await logado(sessoes, ("GESTOR_DADOS", GLOBAL))
    await _equipamentos(sessoes)
    tipo = await _tipo(sessoes, "MATERNIDADE")

    resposta = await cliente.patch(
        ROTA.format(id=tipo), json={"codigo": "POLICLINICA"}, headers=bearer(app, gestor)
    )

    assert resposta.status_code == 409
    assert resposta.json()["title"] == "Conflito"
    assert await _codigos_dos_equipamentos(sessoes) == [
        "MATERNIDADE",
        "MATERNIDADE",
        "POLICLINICA",
    ]
    assert await eventos(sessoes, "referencia.atualizada") == []


async def test_tipo_inexistente_responde_404(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """011/R9.2 (design § Rotas: 404)."""
    gestor = await logado(sessoes, ("GESTOR_DADOS", GLOBAL))

    resposta = await cliente.patch(
        ROTA.format(id=32000), json={"codigo": "NOVO"}, headers=bearer(app, gestor)
    )

    assert resposta.status_code == 404
    assert await eventos(sessoes, "referencia.atualizada") == []


async def test_quem_nao_e_gestor_de_dados_responde_403_e_nada_muda(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """006/R7.2: só o `GESTOR_DADOS` (`regra_validacao:manage`) corrige o código."""
    usuario = await logado(sessoes, ("ADMIN_TI", GLOBAL))
    await _equipamentos(sessoes)
    tipo = await _tipo(sessoes, "MATERNIDADE")

    resposta = await cliente.patch(
        ROTA.format(id=tipo), json={"codigo": "MATERNIDADE_MUN"}, headers=bearer(app, usuario)
    )

    assert resposta.status_code == 403
    assert "MATERNIDADE_MUN" not in await _codigos_dos_equipamentos(sessoes)
