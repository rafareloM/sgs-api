"""Inventário da rede pela API (spec 011, R4.1 a R4.3; design § Rotas e § Consultas).

Cada teste semeia o próprio cadastro, direto no banco pelo dono, e confere que a rota devolve, a
partir da `vw_unit_inventory`, as contagens e a situação cadastral do semeado, sem dado pessoal,
no escopo de leitura do usuário (spec 003) e nos filtros de distrito e de tipo.
"""

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker

from src.core.ids import uuid7
from src.main import create_app
from tests.factories import make_settings
from tests.integration.acesso import GLOBAL, Sessoes, bearer, id_pelo_codigo, logado
from tests.integration.postgres import BancoDeTeste, motor
from tests.integration.registry.cadastro import (
    inserir_equipamento,
    inserir_servico,
    inserir_unidade,
)

INVENTARIO = "/api/v1/dashboard/consultas/inventario"

# Id de referência no formato certo que não existe (a 0006 semeia 8 distritos e 7 tipos).
INEXISTENTE = 999

# Campos de cada item: as colunas da `vw_unit_inventory`, sem dado pessoal (011/R4.2).
CAMPOS = {
    "id",
    "nome",
    "cnes",
    "status",
    "situacao_cadastral",
    "tipo_id",
    "tipo",
    "area_tecnica_id",
    "area_tecnica",
    "distrito_id",
    "distrito",
    "equipamentos",
    "servicos",
    "servicos_fora_cnes",
}


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
    """Conexão do dono do banco (superusuário), para semear o cadastro e papéis de teste. O teste
    confirma com `commit()` antes de chamar a API."""
    engine = motor(banco.url_dono)
    async with engine.connect() as conexao:
        yield conexao
    await engine.dispose()


# Na matriz semeada (0003), todo papel com `dashboard:read` o tem com escopo máximo global (ver
# "Escopo de `dashboard:read` nas consultas" nas perguntas da 011). Para exercitar o escopo de
# leitura (011/R4.3), o teste cria um papel com `dashboard:read` limitado ao distrito.
PAINEL_DISTRITAL = "PAINEL_DISTRITAL_TESTE"


async def _criar_painel_distrital(dono: AsyncConnection) -> None:
    papel = uuid7()
    await dono.execute(
        text(
            "INSERT INTO roles (id, code, name, description)"
            " VALUES (:id, :codigo, 'Painel distrital (teste)', 'Dashboard do próprio distrito.')"
        ),
        {"id": papel, "codigo": PAINEL_DISTRITAL},
    )
    await dono.execute(
        text(
            "INSERT INTO role_permissions (role_id, permission_id, max_scope)"
            " SELECT :papel, id, 'distrito' FROM permissions WHERE code = 'dashboard:read'"
        ),
        {"papel": papel},
    )


async def _atualizar(dono: AsyncConnection, unidade: UUID, atribuicoes: str) -> None:
    await dono.execute(
        text(f"UPDATE health_units SET {atribuicoes} WHERE id = :id"),  # noqa: S608 (texto fixo)
        {"id": unidade},
    )


async def _ids(sessoes: Sessoes) -> dict[str, int]:
    return {
        "DS-I": await id_pelo_codigo(sessoes, "distrito", "DS-I"),
        "DS-III": await id_pelo_codigo(sessoes, "distrito", "DS-III"),
        "CAPS_II": await id_pelo_codigo(sessoes, "tipo_unidade", "CAPS_II"),
        "USF": await id_pelo_codigo(sessoes, "tipo_unidade", "USF"),
        "SAUDE_MENTAL": await id_pelo_codigo(sessoes, "area", "SAUDE_MENTAL"),
        "APS": await id_pelo_codigo(sessoes, "area", "APS"),
    }


def _caps_ds1(ids: dict[str, int]) -> dict[str, Any]:
    return {
        "tipo_id": ids["CAPS_II"],
        "tipo": "CAPS II",
        "area_tecnica_id": ids["SAUDE_MENTAL"],
        "area_tecnica": "Saúde Mental",
        "distrito_id": ids["DS-I"],
        "distrito": "Distrito Sanitário I",
    }


def _usf_ds3(ids: dict[str, int]) -> dict[str, Any]:
    return {
        "tipo_id": ids["USF"],
        "tipo": "Unidade de Saúde da Família",
        "area_tecnica_id": ids["APS"],
        "area_tecnica": "Atenção Primária à Saúde",
        "distrito_id": ids["DS-III"],
        "distrito": "Distrito Sanitário III",
    }


async def test_inventario_traz_contagens_e_situacao_cadastral_de_cada_unidade(
    app: FastAPI,
    cliente: httpx.AsyncClient,
    sessoes: Sessoes,
    dono: AsyncConnection,
) -> None:
    """011/R4.1, R4.3, R5.3: uma linha por unidade, com tipo, área técnica, distrito, status,
    situação cadastral e as quantidades de equipamentos, serviços e serviços fora do CNES.
    Equipamento sem unidade e serviço solto não contam para nenhuma."""
    regular = await inserir_unidade(dono, "CAPS Espaço Azul", cnes="2711907")
    for nome in ("Policlínica Boa Vista", "Policlínica Torre"):
        await inserir_equipamento(dono, regular, nome=nome, tipo="POLICLINICA")
    await inserir_servico(dono, regular, nome="Farmácia do CAPS")
    await inserir_servico(dono, regular, nome="Acolhimento noturno", no_cnes=True)
    await inserir_servico(dono, regular, nome="Oficina terapêutica", no_cnes=True)
    pendente = await inserir_unidade(dono, "CAPS Galdino Loreto", cnes="2711908")
    await _atualizar(dono, pendente, "pending_issues = 2")
    sem_cnes = await inserir_unidade(dono, "USF Ibura", distrito="DS-III", tipo="USF")
    await inserir_servico(dono, sem_cnes, nome="Sala de vacina da USF", no_cnes=True)
    inativa = await inserir_unidade(dono, "USF Fechada", distrito="DS-III", tipo="USF")
    await _atualizar(dono, inativa, "status = 'inativa'")
    await inserir_equipamento(dono, None, nome="UTI móvel Norte", tipo="UTI_MOVEL")
    await inserir_servico(dono, None, nome="Sala de Vacinação do Shopping", tipo="SALA_VACINA")
    await dono.commit()
    ids = await _ids(sessoes)
    gestor = await logado(sessoes, ("GESTOR_DADOS", GLOBAL))

    resposta = await cliente.get(INVENTARIO, headers=bearer(app, gestor))

    assert resposta.status_code == 200
    assert resposta.json() == {
        "itens": [
            {
                "id": str(regular),
                "nome": "CAPS Espaço Azul",
                "cnes": "2711907",
                "status": "ativa",
                "situacao_cadastral": "regular",
                **_caps_ds1(ids),
                "equipamentos": 2,
                "servicos": 3,
                "servicos_fora_cnes": 1,
            },
            {
                "id": str(pendente),
                "nome": "CAPS Galdino Loreto",
                "cnes": "2711908",
                "status": "ativa",
                "situacao_cadastral": "com_pendencias",
                **_caps_ds1(ids),
                "equipamentos": 0,
                "servicos": 0,
                "servicos_fora_cnes": 0,
            },
            {
                "id": str(inativa),
                "nome": "USF Fechada",
                "cnes": None,
                "status": "inativa",
                "situacao_cadastral": "inativa",
                **_usf_ds3(ids),
                "equipamentos": 0,
                "servicos": 0,
                "servicos_fora_cnes": 0,
            },
            {
                "id": str(sem_cnes),
                "nome": "USF Ibura",
                "cnes": None,
                "status": "ativa",
                "situacao_cadastral": "sem_cnes",
                **_usf_ds3(ids),
                "equipamentos": 0,
                "servicos": 1,
                "servicos_fora_cnes": 0,
            },
        ],
        "total": 4,
        "pagina": 1,
        "tamanho": 20,
    }


async def test_inventario_nao_traz_nenhum_dado_pessoal(
    app: FastAPI,
    cliente: httpx.AsyncClient,
    sessoes: Sessoes,
    dono: AsyncConnection,
) -> None:
    """011/R4.2: nem o nome do gestor nem o contato da unidade aparecem no inventário."""
    unidade = await inserir_unidade(dono, "CAPS Espaço Azul")
    await _atualizar(
        dono,
        unidade,
        "manager_name = 'Maria José da Silva', phone = '8133551234', neighborhood = 'Boa Vista'",
    )
    await dono.commit()
    gestor = await logado(sessoes, ("GESTOR_DADOS", GLOBAL))

    resposta = await cliente.get(INVENTARIO, headers=bearer(app, gestor))

    assert resposta.status_code == 200
    [item] = resposta.json()["itens"]
    assert set(item) == CAMPOS
    for dado_pessoal in ("Maria José", "8133551234", "Boa Vista", "Rua do Sol", "50010100"):
        assert dado_pessoal not in resposta.text


async def test_inventario_com_escopo_distrital_lista_so_as_unidades_do_distrito(
    app: FastAPI,
    cliente: httpx.AsyncClient,
    sessoes: Sessoes,
    dono: AsyncConnection,
) -> None:
    """011/R4.3: o escopo de leitura do usuário (spec 003) limita o inventário."""
    await inserir_unidade(dono, "CAPS Espaço Azul", distrito="DS-I")
    usf = await inserir_unidade(dono, "USF Ibura", distrito="DS-III", tipo="USF")
    await _criar_painel_distrital(dono)
    await dono.commit()
    ds3 = await id_pelo_codigo(sessoes, "distrito", "DS-III")
    tecnico = await logado(sessoes, (PAINEL_DISTRITAL, ("distrito", str(ds3))))

    resposta = await cliente.get(INVENTARIO, headers=bearer(app, tecnico))

    assert resposta.status_code == 200
    assert [item["id"] for item in resposta.json()["itens"]] == [str(usf)]
    assert resposta.json()["total"] == 1


async def test_inventario_filtra_por_distrito_e_por_tipo(
    app: FastAPI,
    cliente: httpx.AsyncClient,
    sessoes: Sessoes,
    dono: AsyncConnection,
) -> None:
    """011/R4.3, R2.7: filtro por distrito e por tipo de unidade, combináveis."""
    caps_ds1 = await inserir_unidade(dono, "CAPS David Capistrano", distrito="DS-I")
    usf_ds1 = await inserir_unidade(dono, "USF Coque", distrito="DS-I", tipo="USF")
    caps_ds3 = await inserir_unidade(dono, "CAPS Galdino Loreto", distrito="DS-III")
    usf_ds3 = await inserir_unidade(dono, "USF Ibura", distrito="DS-III", tipo="USF")
    await dono.commit()
    ds3 = await id_pelo_codigo(sessoes, "distrito", "DS-III")
    usf = await id_pelo_codigo(sessoes, "tipo_unidade", "USF")
    gestor = await logado(sessoes, ("GESTOR_DADOS", GLOBAL))

    async def ids(**filtros: int) -> list[str]:
        resposta = await cliente.get(INVENTARIO, params=filtros, headers=bearer(app, gestor))
        assert resposta.status_code == 200
        return [item["id"] for item in resposta.json()["itens"]]

    assert await ids() == [str(caps_ds1), str(usf_ds1), str(caps_ds3), str(usf_ds3)]
    assert await ids(distrito=ds3) == [str(caps_ds3), str(usf_ds3)]
    assert await ids(tipo=usf) == [str(usf_ds1), str(usf_ds3)]
    assert await ids(distrito=ds3, tipo=usf) == [str(usf_ds3)]


async def test_inventario_pagina_o_resultado(
    app: FastAPI,
    cliente: httpx.AsyncClient,
    sessoes: Sessoes,
    dono: AsyncConnection,
) -> None:
    """011/R4.3 e design § Rotas: `PaginaOut`, com o total da consulta inteira em toda página."""
    nomes = ["CAPS A", "CAPS B", "CAPS C"]
    unidades = [await inserir_unidade(dono, nome) for nome in nomes]
    await dono.commit()
    gestor = await logado(sessoes, ("GESTOR_DADOS", GLOBAL))

    async def pagina(numero: int) -> dict[str, Any]:
        resposta = await cliente.get(
            INVENTARIO, params={"pagina": numero, "tamanho": 2}, headers=bearer(app, gestor)
        )
        assert resposta.status_code == 200
        corpo: dict[str, Any] = resposta.json()
        return corpo

    primeira, segunda, depois = await pagina(1), await pagina(2), await pagina(3)
    assert [item["id"] for item in primeira["itens"]] == [str(u) for u in unidades[:2]]
    assert [item["id"] for item in segunda["itens"]] == [str(unidades[2])]
    assert depois["itens"] == []
    assert (primeira["total"], segunda["total"], depois["total"]) == (3, 3, 3)
    assert (segunda["pagina"], segunda["tamanho"]) == (2, 2)


# Testes negativos de segurança da rota (steering/testing.md).


async def test_inventario_sem_token_responde_401(cliente: httpx.AsyncClient) -> None:
    """011/R4.3: rota protegida."""
    resposta = await cliente.get(INVENTARIO)

    assert resposta.status_code == 401
    assert resposta.headers["content-type"] == "application/problem+json"


async def test_inventario_sem_dashboard_read_responde_403(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """011/R4.3: só quem tem `dashboard:read` consulta o inventário."""
    # AUDITOR tem escopo global, mas não tem `dashboard:read` (matriz da 0003).
    auditor = await logado(sessoes, ("AUDITOR", GLOBAL))

    resposta = await cliente.get(INVENTARIO, headers=bearer(app, auditor))

    assert resposta.status_code == 403
    assert resposta.headers["content-type"] == "application/problem+json"


async def test_inventario_com_distrito_ou_tipo_inexistente_responde_422(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """011/R4.3, R2.9: filtro que aponta para referência inexistente dá 422."""
    gestor = await logado(sessoes, ("GESTOR_DADOS", GLOBAL))

    resposta = await cliente.get(
        INVENTARIO,
        params={"distrito": INEXISTENTE, "tipo": INEXISTENTE},
        headers=bearer(app, gestor),
    )

    assert resposta.status_code == 422
    assert resposta.headers["content-type"] == "application/problem+json"
    assert resposta.json()["errors"] == [
        {"campo": "distrito", "mensagem": "Distrito inexistente."},
        {"campo": "tipo", "mensagem": "Tipo de unidade inexistente."},
    ]


@pytest.mark.parametrize(
    ("params", "campo"),
    [
        ({"distrito": "DS-III"}, "distrito"),
        ({"tipo": "0"}, "tipo"),
        ({"distrito": "40000"}, "distrito"),
        ({"pagina": "0"}, "pagina"),
        ({"tamanho": "101"}, "tamanho"),
    ],
)
async def test_inventario_com_filtro_mal_formado_responde_422(
    app: FastAPI,
    cliente: httpx.AsyncClient,
    sessoes: Sessoes,
    params: dict[str, str],
    campo: str,
) -> None:
    """011/R4.3, R2.9: filtro ou página em formato inválido dá 422."""
    gestor = await logado(sessoes, ("GESTOR_DADOS", GLOBAL))

    resposta = await cliente.get(INVENTARIO, params=params, headers=bearer(app, gestor))

    assert resposta.status_code == 422
    assert [erro["campo"] for erro in resposta.json()["errors"]] == [campo]
