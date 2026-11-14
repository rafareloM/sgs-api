"""Equipamentos de uma unidade e equipamentos sem unidade (006/T7).

Design da 006 § Rotas e § Diff e auditoria: `GET /unidades/{id}/equipamentos` com
`unidade:read`; `POST`, `PATCH .../{eid}` e `DELETE .../{eid}` com `equipamento:write` no escopo
da unidade (R5.1); `GET/POST /equipamentos`, só para quem tem `equipamento:write` global, o
Gestor de Dados (R5.2). As mudanças em equipamento de unidade são auditadas no nível da unidade,
como `unidade.equipamento_*` (R5.3).
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
from tests.integration.registry.cadastro import (
    inserir_equipamento,
    inserir_servico,
    inserir_unidade,
)

ROTA = "/api/v1/unidades/{id}/equipamentos"
ROTA_DO_EQUIPAMENTO = "/api/v1/unidades/{id}/equipamentos/{eid}"
ROTA_SEM_UNIDADE = "/api/v1/equipamentos"

MATERNIDADE = {
    "nome": "Maternidade Bandeira Filho",
    "cnes": "0000396",
    "tipo_equipamento_codigo": "MATERNIDADE",
    "quantidade": 2,
    "status": "ativo",
}


def _rota(unidade: UUID) -> str:
    return ROTA.format(id=unidade)


def _rota_do_equipamento(unidade: UUID, equipamento: UUID) -> str:
    return ROTA_DO_EQUIPAMENTO.format(id=unidade, eid=equipamento)


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


async def _unidade(sessoes: Sessoes, nome: str = "Policlínica Lessa de Andrade") -> UUID:
    """CAPS II (Saúde Mental) no DS I."""
    async with sessoes() as sessao, sessao.begin():
        return await inserir_unidade(await sessao.connection(), nome)


async def _equipamento(sessoes: Sessoes, unidade: UUID | None, **campos: str) -> UUID:
    async with sessoes() as sessao, sessao.begin():
        return await inserir_equipamento(await sessao.connection(), unidade, **campos)


async def _gravados(sessoes: Sessoes) -> list[dict[str, Any]]:
    """Os equipamentos como estão no banco, pela ordem do id."""
    async with sessoes() as sessao:
        resultado = await sessao.execute(
            text(
                "SELECT id, unit_id, name, cnes, equipment_type_code, quantity, status"
                " FROM equipments ORDER BY id"
            )
        )
        return [dict(linha) for linha in resultado.mappings()]


async def _gestor_da_unidade(sessoes: Sessoes, unidade: UUID) -> Any:
    return await logado(sessoes, ("GESTOR_UNIDADE", ("unidade", str(unidade))))


# --- Equipamentos da unidade (R5.1, R5.3) ---------------------------------------------------


async def test_gestor_da_unidade_adiciona_equipamento_auditado_na_unidade(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """006/R5.1, 006/R5.3: 201 com o equipamento; `unidade.equipamento_criado` com a unidade
    como entidade, todos os campos e o id do equipamento nos metadados."""
    unidade = await _unidade(sessoes)
    gestor = await _gestor_da_unidade(sessoes, unidade)

    resposta = await cliente.post(_rota(unidade), json=MATERNIDADE, headers=bearer(app, gestor))

    assert resposta.status_code == 201
    corpo = resposta.json()
    equipamento = corpo.pop("id")
    assert resposta.headers["location"] == _rota_do_equipamento(unidade, equipamento)
    assert set(corpo) == {"unidade_id", *MATERNIDADE, "criado_em", "atualizado_em"}
    assert corpo["unidade_id"] == str(unidade)
    assert {campo: corpo[campo] for campo in MATERNIDADE} == MATERNIDADE
    [gravado] = await _gravados(sessoes)
    assert gravado == {
        "id": UUID(equipamento),
        "unit_id": unidade,
        "name": "Maternidade Bandeira Filho",
        "cnes": "0000396",
        "equipment_type_code": "MATERNIDADE",
        "quantity": 2,
        "status": "ativo",
    }
    assert await eventos(sessoes, "unidade.equipamento_criado") == [
        {
            "actor_user_id": gestor.user_id,
            "session_id": gestor.id,
            "entity_type": "unidade",
            "entity_id": str(unidade),
            "changes": [
                {"campo": "equipamento.nome", "de": None, "para": "Maternidade Bandeira Filho"},
                {"campo": "equipamento.cnes", "de": None, "para": "0000396"},
                {"campo": "equipamento.tipo_equipamento_codigo", "de": None, "para": "MATERNIDADE"},
                {"campo": "equipamento.quantidade", "de": None, "para": 2},
                {"campo": "equipamento.status", "de": None, "para": "ativo"},
            ],
            "metadata": {"equipamento_id": equipamento},
        }
    ]


async def test_equipamento_sem_cnes_nem_quantidade_vale_um(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """006/R5.1: CNES é opcional e a quantidade padrão é 1, como no banco."""
    unidade = await _unidade(sessoes)
    gestor = await _gestor_da_unidade(sessoes, unidade)
    corpo = {"nome": "Policlínica", "tipo_equipamento_codigo": "POLICLINICA", "status": "ativo"}

    resposta = await cliente.post(_rota(unidade), json=corpo, headers=bearer(app, gestor))

    assert resposta.status_code == 201
    assert resposta.json()["cnes"] is None
    assert resposta.json()["quantidade"] == 1


async def test_lista_so_os_equipamentos_da_unidade(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """006/R5.1: com `unidade:read`, os equipamentos da unidade, sem os de outra nem os sem
    unidade."""
    unidade = await _unidade(sessoes)
    outra = await _unidade(sessoes, "CAPS Galdino Loreto")
    maternidade = await _equipamento(sessoes, unidade)
    policlinica = await _equipamento(sessoes, unidade, nome="Policlínica", tipo="POLICLINICA")
    await _equipamento(sessoes, outra)
    await _equipamento(sessoes, None, nome="UTI móvel 01", tipo="UTI_MOVEL")
    diretoria = await logado(sessoes, ("DIRETORIA", GLOBAL))

    resposta = await cliente.get(_rota(unidade), headers=bearer(app, diretoria))

    assert resposta.status_code == 200
    assert [(e["id"], e["nome"]) for e in resposta.json()] == [
        (str(maternidade), "Maternidade Bandeira Filho"),
        (str(policlinica), "Policlínica"),
    ]


async def test_listar_de_unidade_inexistente_responde_404(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """006/R5.1, 003/R4.3: com a permissão, unidade que não existe dá 404."""
    diretoria = await logado(sessoes, ("DIRETORIA", GLOBAL))

    resposta = await cliente.get(
        _rota(UUID("0197a000-0000-7000-8000-000000000001")), headers=bearer(app, diretoria)
    )

    assert resposta.status_code == 404


async def test_altera_so_os_campos_enviados_e_audita_o_que_mudou(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """006/R5.1, 006/R5.3: 200 com o equipamento; `unidade.equipamento_atualizado` só com os
    campos que mudaram."""
    unidade = await _unidade(sessoes)
    equipamento = await _equipamento(sessoes, unidade)
    gestor = await _gestor_da_unidade(sessoes, unidade)

    resposta = await cliente.patch(
        _rota_do_equipamento(unidade, equipamento),
        json={"nome": "Maternidade Bandeira Filho", "quantidade": 3, "status": "inativo"},
        headers=bearer(app, gestor),
    )

    assert resposta.status_code == 200
    assert resposta.json()["quantidade"] == 3
    assert resposta.json()["status"] == "inativo"
    [gravado] = await _gravados(sessoes)
    assert (gravado["name"], gravado["quantity"], gravado["status"]) == (
        "Maternidade Bandeira Filho",
        3,
        "inativo",
    )
    [evento] = await eventos(sessoes, "unidade.equipamento_atualizado")
    assert (evento["entity_type"], evento["entity_id"]) == ("unidade", str(unidade))
    assert evento["changes"] == [
        {"campo": "equipamento.quantidade", "de": 1, "para": 3},
        {"campo": "equipamento.status", "de": "ativo", "para": "inativo"},
    ]
    assert evento["metadata"] == {"equipamento_id": str(equipamento)}


async def test_alteracao_sem_mudanca_nao_audita(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """006/R5.3: nada mudou, nada a auditar (como a unidade, R3.6)."""
    unidade = await _unidade(sessoes)
    equipamento = await _equipamento(sessoes, unidade)
    gestor = await _gestor_da_unidade(sessoes, unidade)

    resposta = await cliente.patch(
        _rota_do_equipamento(unidade, equipamento),
        json={"status": "ativo"},
        headers=bearer(app, gestor),
    )

    assert resposta.status_code == 200
    assert await eventos(sessoes, "unidade.equipamento_atualizado") == []


async def test_remove_equipamento_mantem_servicos_na_unidade_e_audita(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """006/R5.1, 006/R5.3, 011/R9.1: 204; o equipamento sai do banco, o serviço dele continua
    na unidade, e `unidade.equipamento_removido` leva os campos que ele tinha."""
    unidade = await _unidade(sessoes)
    equipamento = await _equipamento(sessoes, unidade)
    async with sessoes() as sessao, sessao.begin():
        servico = await inserir_servico(await sessao.connection(), unidade, equipamento=equipamento)
    gestor = await _gestor_da_unidade(sessoes, unidade)

    resposta = await cliente.delete(
        _rota_do_equipamento(unidade, equipamento), headers=bearer(app, gestor)
    )

    assert resposta.status_code == 204
    assert await _gravados(sessoes) == []
    async with sessoes() as sessao:
        linha = (
            await sessao.execute(
                text("SELECT unit_id, equipment_id FROM services WHERE id = :id"), {"id": servico}
            )
        ).one()
    assert tuple(linha) == (unidade, None)
    [evento] = await eventos(sessoes, "unidade.equipamento_removido")
    assert (evento["entity_type"], evento["entity_id"]) == ("unidade", str(unidade))
    assert evento["changes"] == [
        {"campo": "equipamento.nome", "de": "Maternidade Bandeira Filho", "para": None},
        {"campo": "equipamento.cnes", "de": None, "para": None},
        {"campo": "equipamento.tipo_equipamento_codigo", "de": "MATERNIDADE", "para": None},
        {"campo": "equipamento.quantidade", "de": 1, "para": None},
        {"campo": "equipamento.status", "de": "ativo", "para": None},
    ]
    assert evento["metadata"] == {"equipamento_id": str(equipamento)}


@pytest.mark.parametrize("metodo", ["PATCH", "DELETE"])
async def test_equipamento_de_outra_unidade_responde_404_e_nada_muda(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes, metodo: str
) -> None:
    """006/R5.1: o equipamento é procurado só entre os da unidade da rota."""
    unidade = await _unidade(sessoes)
    outra = await _unidade(sessoes, "CAPS Galdino Loreto")
    equipamento = await _equipamento(sessoes, outra)
    gestor = await _gestor_da_unidade(sessoes, unidade)
    antes = await _gravados(sessoes)

    resposta = await cliente.request(
        metodo,
        _rota_do_equipamento(unidade, equipamento),
        json={"quantidade": 5} if metodo == "PATCH" else None,
        headers=bearer(app, gestor),
    )

    assert resposta.status_code == 404
    assert await _gravados(sessoes) == antes


async def _atribuicao(sessoes: Sessoes, papel: str, unidade: UUID) -> Atribuicao:
    """O papel com escopo que não cobre a unidade (CAPS II, Saúde Mental, DS I)."""
    escopos = {
        "COORD_TECNICO": ("area", str(await id_pelo_codigo(sessoes, "area", "APS"))),
        "TECNICO_DISTRITAL": ("distrito", str(await id_pelo_codigo(sessoes, "distrito", "DS-II"))),
        "GESTOR_UNIDADE": ("unidade", str(await _unidade(sessoes, "USF Outra"))),
    }
    return papel, escopos.get(papel, GLOBAL)


@pytest.mark.parametrize(
    "papel",
    ["COORD_TECNICO", "TECNICO_DISTRITAL", "GESTOR_UNIDADE", "DIRETORIA", "AUDITOR", "ADMIN_TI"],
)
@pytest.mark.parametrize("metodo", ["POST", "PATCH", "DELETE"])
async def test_sem_equipamento_write_no_escopo_da_unidade_responde_403_e_nada_muda(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes, papel: str, metodo: str
) -> None:
    """006/R5.1, 003/R4.3, 003/R4.6: fora do escopo da unidade, ou sem a permissão, 403
    auditado com a unidade; nada muda."""
    unidade = await _unidade(sessoes)
    equipamento = await _equipamento(sessoes, unidade)
    usuario = await logado(sessoes, await _atribuicao(sessoes, papel, unidade))
    antes = await _gravados(sessoes)
    rota, molde = (
        (_rota(unidade), ROTA)
        if metodo == "POST"
        else (_rota_do_equipamento(unidade, equipamento), ROTA_DO_EQUIPAMENTO)
    )

    resposta = await cliente.request(
        metodo,
        rota,
        json={"POST": MATERNIDADE, "PATCH": {"quantidade": 5}}.get(metodo),
        headers=bearer(app, usuario),
    )

    assert resposta.status_code == 403
    [negacao] = await eventos(sessoes, "acesso.negado")
    assert (negacao["entity_type"], negacao["entity_id"]) == ("unidade", str(unidade))
    assert negacao["metadata"] == {"permissao": "equipamento:write", "rota": f"{metodo} {molde}"}
    assert await _gravados(sessoes) == antes


@pytest.mark.parametrize(
    "papel", ["COORD_TECNICO", "TECNICO_DISTRITAL", "GESTOR_UNIDADE", "GESTOR_DADOS"]
)
async def test_quem_tem_equipamento_write_no_escopo_da_unidade_adiciona(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes, papel: str
) -> None:
    """006/R5.1: `equipamento:write` na área, no distrito, na unidade ou global basta."""
    unidade = await _unidade(sessoes)
    escopos = {
        "COORD_TECNICO": ("area", str(await id_pelo_codigo(sessoes, "area", "SAUDE_MENTAL"))),
        "TECNICO_DISTRITAL": ("distrito", str(await id_pelo_codigo(sessoes, "distrito", "DS-I"))),
        "GESTOR_UNIDADE": ("unidade", str(unidade)),
    }
    usuario = await logado(sessoes, (papel, escopos.get(papel, GLOBAL)))

    resposta = await cliente.post(_rota(unidade), json=MATERNIDADE, headers=bearer(app, usuario))

    assert resposta.status_code == 201


@pytest.mark.parametrize("codigo", ["NAO_EXISTE", "UTI_MOVEL"], ids=["inexistente", "desativado"])
@pytest.mark.parametrize("metodo", ["POST", "PATCH"])
async def test_tipo_inexistente_ou_desativado_responde_422_e_nada_muda(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes, codigo: str, metodo: str
) -> None:
    """006/R5.1: o tipo de equipamento tem de existir e estar ativo, como as referências da
    unidade (R1.2)."""
    async with sessoes() as sessao, sessao.begin():
        await sessao.execute(
            text("UPDATE equipment_types SET is_active = false WHERE code = 'UTI_MOVEL'")
        )
    unidade = await _unidade(sessoes)
    equipamento = await _equipamento(sessoes, unidade)
    gestor = await _gestor_da_unidade(sessoes, unidade)
    antes = await _gravados(sessoes)

    if metodo == "POST":
        resposta = await cliente.post(
            _rota(unidade),
            json={**MATERNIDADE, "tipo_equipamento_codigo": codigo},
            headers=bearer(app, gestor),
        )
    else:
        resposta = await cliente.patch(
            _rota_do_equipamento(unidade, equipamento),
            json={"tipo_equipamento_codigo": codigo},
            headers=bearer(app, gestor),
        )

    assert resposta.status_code == 422
    assert [erro["campo"] for erro in resposta.json()["errors"]] == ["tipo_equipamento_codigo"]
    assert await _gravados(sessoes) == antes


@pytest.mark.parametrize(
    ("corpo", "campo"),
    [
        ({**MATERNIDADE, "nome": ""}, "nome"),
        ({**MATERNIDADE, "cnes": "123"}, "cnes"),
        ({**MATERNIDADE, "quantidade": 0}, "quantidade"),
        ({**MATERNIDADE, "status": "quebrado"}, "status"),
        ({k: v for k, v in MATERNIDADE.items() if k != "status"}, "status"),
        ({**MATERNIDADE, "unidade_id": None}, "unidade_id"),
    ],
    ids=["nome-vazio", "cnes-curto", "quantidade-zero", "status-invalido", "sem-status", "extra"],
)
async def test_corpo_invalido_responde_422(
    app: FastAPI,
    cliente: httpx.AsyncClient,
    sessoes: Sessoes,
    corpo: dict[str, Any],
    campo: str,
) -> None:
    """006/R5.1: formato conferido no schema; nada é gravado."""
    unidade = await _unidade(sessoes)
    gestor = await _gestor_da_unidade(sessoes, unidade)

    resposta = await cliente.post(_rota(unidade), json=corpo, headers=bearer(app, gestor))

    assert resposta.status_code == 422
    assert [erro["campo"] for erro in resposta.json()["errors"]] == [campo]
    assert await _gravados(sessoes) == []


@pytest.mark.parametrize("campo", ["nome", "tipo_equipamento_codigo", "quantidade", "status"])
async def test_patch_com_obrigatorio_nulo_responde_422(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes, campo: str
) -> None:
    """006/R5.1: no PATCH, o que é obrigatório no cadastro pode faltar, mas não vir nulo."""
    unidade = await _unidade(sessoes)
    equipamento = await _equipamento(sessoes, unidade)
    gestor = await _gestor_da_unidade(sessoes, unidade)

    resposta = await cliente.patch(
        _rota_do_equipamento(unidade, equipamento), json={campo: None}, headers=bearer(app, gestor)
    )

    assert resposta.status_code == 422
    assert [erro["campo"] for erro in resposta.json()["errors"]] == [campo]


@pytest.mark.parametrize(
    ("metodo", "rota"),
    [
        ("GET", ROTA),
        ("POST", ROTA),
        ("PATCH", ROTA_DO_EQUIPAMENTO),
        ("DELETE", ROTA_DO_EQUIPAMENTO),
    ],
)
async def test_sem_bearer_responde_401(
    cliente: httpx.AsyncClient, sessoes: Sessoes, metodo: str, rota: str
) -> None:
    """003/R4.1: as rotas exigem autenticação; nada muda."""
    unidade = await _unidade(sessoes)
    equipamento = await _equipamento(sessoes, unidade)
    antes = await _gravados(sessoes)

    resposta = await cliente.request(
        metodo,
        rota.format(id=unidade, eid=equipamento),
        json={"POST": MATERNIDADE, "PATCH": {"quantidade": 5}}.get(metodo),
    )

    assert resposta.status_code == 401
    assert await _gravados(sessoes) == antes


# --- Equipamentos sem unidade (R5.2) --------------------------------------------------------


async def test_gestor_de_dados_cadastra_equipamento_sem_unidade_auditado(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """006/R5.2: 201 com `unidade_id` nulo; `equipamento.criado` com o próprio equipamento como
    entidade, porque não há unidade."""
    gestor = await logado(sessoes, ("GESTOR_DADOS", GLOBAL))
    corpo = {"nome": "UTI móvel 01", "tipo_equipamento_codigo": "UTI_MOVEL", "status": "ativo"}

    resposta = await cliente.post(ROTA_SEM_UNIDADE, json=corpo, headers=bearer(app, gestor))

    assert resposta.status_code == 201
    equipamento = resposta.json()["id"]
    assert resposta.json()["unidade_id"] is None
    [gravado] = await _gravados(sessoes)
    assert (gravado["unit_id"], gravado["name"]) == (None, "UTI móvel 01")
    assert await eventos(sessoes, "equipamento.criado") == [
        {
            "actor_user_id": gestor.user_id,
            "session_id": gestor.id,
            "entity_type": "equipamento",
            "entity_id": equipamento,
            "changes": [
                {"campo": "nome", "de": None, "para": "UTI móvel 01"},
                {"campo": "cnes", "de": None, "para": None},
                {"campo": "tipo_equipamento_codigo", "de": None, "para": "UTI_MOVEL"},
                {"campo": "quantidade", "de": None, "para": 1},
                {"campo": "status", "de": None, "para": "ativo"},
            ],
            "metadata": {},
        }
    ]


async def test_gestor_de_dados_lista_so_os_equipamentos_sem_unidade(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """006/R5.2: `GET /equipamentos` traz os equipamentos sem unidade."""
    unidade = await _unidade(sessoes)
    await _equipamento(sessoes, unidade)
    uti = await _equipamento(sessoes, None, nome="UTI móvel 01", tipo="UTI_MOVEL")
    gestor = await logado(sessoes, ("GESTOR_DADOS", GLOBAL))

    resposta = await cliente.get(ROTA_SEM_UNIDADE, headers=bearer(app, gestor))

    assert resposta.status_code == 200
    assert [(e["id"], e["unidade_id"]) for e in resposta.json()] == [(str(uti), None)]


@pytest.mark.parametrize(
    "papel",
    ["COORD_TECNICO", "TECNICO_DISTRITAL", "GESTOR_UNIDADE", "DIRETORIA", "AUDITOR", "ADMIN_TI"],
)
@pytest.mark.parametrize("metodo", ["GET", "POST"])
async def test_so_gestor_de_dados_usa_equipamentos_sem_unidade(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes, papel: str, metodo: str
) -> None:
    """006/R5.2, 003/R4.6: `equipamento:write` com escopo de área, distrito ou unidade não
    basta; 403 auditado, sem entidade, e nada é gravado."""
    unidade = await _unidade(sessoes)
    escopos = {
        "COORD_TECNICO": ("area", str(await id_pelo_codigo(sessoes, "area", "SAUDE_MENTAL"))),
        "TECNICO_DISTRITAL": ("distrito", str(await id_pelo_codigo(sessoes, "distrito", "DS-I"))),
        "GESTOR_UNIDADE": ("unidade", str(unidade)),
    }
    usuario = await logado(sessoes, (papel, escopos.get(papel, GLOBAL)))
    corpo = {"nome": "UTI móvel 01", "tipo_equipamento_codigo": "UTI_MOVEL", "status": "ativo"}

    resposta = await cliente.request(
        metodo,
        ROTA_SEM_UNIDADE,
        json=corpo if metodo == "POST" else None,
        headers=bearer(app, usuario),
    )

    assert resposta.status_code == 403
    [negacao] = await eventos(sessoes, "acesso.negado")
    assert negacao["entity_type"] is None
    assert negacao["metadata"] == {
        "permissao": "equipamento:write",
        "rota": f"{metodo} {ROTA_SEM_UNIDADE}",
    }
    assert await _gravados(sessoes) == []
    assert await eventos(sessoes, "equipamento.criado") == []


@pytest.mark.parametrize("metodo", ["GET", "POST"])
async def test_equipamentos_sem_unidade_sem_bearer_responde_401(
    cliente: httpx.AsyncClient, metodo: str
) -> None:
    """003/R4.1: a rota exige autenticação."""
    resposta = await cliente.request(metodo, ROTA_SEM_UNIDADE, json=MATERNIDADE)

    assert resposta.status_code == 401
