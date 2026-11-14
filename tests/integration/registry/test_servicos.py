"""Serviços de uma unidade e serviços soltos (006/T8).

Design da 006 § Rotas e § Diff e auditoria: `GET /unidades/{id}/servicos` com `unidade:read`;
`POST`, `PATCH .../{sid}` e `DELETE .../{sid}` com `servico:write` no escopo da unidade (R6.1);
`GET/POST /servicos`, só para quem tem `servico:write` global, o Gestor de Dados (R6.2). O
serviço diz se consta no CNES (`no_cnes`, R6.3) e se liga à unidade pelo id, nunca pelo nome
(R6.4). As mudanças em serviço de unidade são auditadas no nível da unidade, como
`unidade.servico_*` (design § Diff e auditoria).
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

ROTA = "/api/v1/unidades/{id}/servicos"
ROTA_DO_SERVICO = "/api/v1/unidades/{id}/servicos/{sid}"
ROTA_SOLTOS = "/api/v1/servicos"


def _rota(unidade: UUID) -> str:
    return ROTA.format(id=unidade)


def _rota_do_servico(unidade: UUID, servico: UUID) -> str:
    return ROTA_DO_SERVICO.format(id=unidade, sid=servico)


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


async def _tipo(sessoes: Sessoes, codigo: str) -> int:
    async with sessoes() as sessao:
        tipo = await sessao.scalar(
            text("SELECT id FROM service_types WHERE code = :code"), {"code": codigo}
        )
    assert isinstance(tipo, int)
    return tipo


async def _farmacia(sessoes: Sessoes) -> dict[str, Any]:
    return {
        "nome": "Farmácia do CAPS",
        "tipo_servico_id": await _tipo(sessoes, "FARMACIA"),
        "no_cnes": True,
        "status": "ativo",
    }


async def _unidade(sessoes: Sessoes, nome: str = "Policlínica Lessa de Andrade") -> UUID:
    """CAPS II (Saúde Mental) no DS I."""
    async with sessoes() as sessao, sessao.begin():
        return await inserir_unidade(await sessao.connection(), nome)


async def _equipamento(sessoes: Sessoes, unidade: UUID | None, **campos: str) -> UUID:
    async with sessoes() as sessao, sessao.begin():
        return await inserir_equipamento(await sessao.connection(), unidade, **campos)


async def _servico(sessoes: Sessoes, unidade: UUID | None, **campos: Any) -> UUID:
    async with sessoes() as sessao, sessao.begin():
        return await inserir_servico(await sessao.connection(), unidade, **campos)


async def _gravados(sessoes: Sessoes) -> list[dict[str, Any]]:
    """Os serviços como estão no banco, pela ordem do id."""
    async with sessoes() as sessao:
        resultado = await sessao.execute(
            text(
                "SELECT id, unit_id, equipment_id, service_type_id, name, in_cnes, status"
                " FROM services ORDER BY id"
            )
        )
        return [dict(linha) for linha in resultado.mappings()]


async def _gestor_da_unidade(sessoes: Sessoes, unidade: UUID) -> Any:
    return await logado(sessoes, ("GESTOR_UNIDADE", ("unidade", str(unidade))))


# --- Serviços da unidade (R6.1, R6.3) -------------------------------------------------------


async def test_gestor_da_unidade_adiciona_servico_auditado_na_unidade(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """006/R6.1, 006/R6.3: 201 com o serviço e `no_cnes`; `unidade.servico_criado` com a
    unidade como entidade, todos os campos e o id do serviço nos metadados."""
    unidade = await _unidade(sessoes)
    gestor = await _gestor_da_unidade(sessoes, unidade)
    farmacia = await _farmacia(sessoes)

    resposta = await cliente.post(_rota(unidade), json=farmacia, headers=bearer(app, gestor))

    assert resposta.status_code == 201
    corpo = resposta.json()
    servico = corpo.pop("id")
    assert resposta.headers["location"] == _rota_do_servico(unidade, servico)
    assert set(corpo) == {
        "unidade_id",
        "equipamento_id",
        *farmacia,
        "criado_em",
        "atualizado_em",
    }
    assert (corpo["unidade_id"], corpo["equipamento_id"]) == (str(unidade), None)
    assert {campo: corpo[campo] for campo in farmacia} == farmacia
    [gravado] = await _gravados(sessoes)
    assert gravado == {
        "id": UUID(servico),
        "unit_id": unidade,
        "equipment_id": None,
        "service_type_id": farmacia["tipo_servico_id"],
        "name": "Farmácia do CAPS",
        "in_cnes": True,
        "status": "ativo",
    }
    assert await eventos(sessoes, "unidade.servico_criado") == [
        {
            "actor_user_id": gestor.user_id,
            "session_id": gestor.id,
            "entity_type": "unidade",
            "entity_id": str(unidade),
            "changes": [
                {
                    "campo": "servico.tipo_servico_id",
                    "de": None,
                    "para": farmacia["tipo_servico_id"],
                },
                {"campo": "servico.equipamento_id", "de": None, "para": None},
                {"campo": "servico.nome", "de": None, "para": "Farmácia do CAPS"},
                {"campo": "servico.no_cnes", "de": None, "para": True},
                {"campo": "servico.status", "de": None, "para": "ativo"},
            ],
            "metadata": {"servico_id": servico},
        }
    ]


async def test_servico_sem_no_cnes_nao_consta_no_cnes(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """006/R6.3: sem `no_cnes`, o serviço não consta no CNES, como o padrão do banco."""
    unidade = await _unidade(sessoes)
    gestor = await _gestor_da_unidade(sessoes, unidade)
    corpo = {k: v for k, v in (await _farmacia(sessoes)).items() if k != "no_cnes"}

    resposta = await cliente.post(_rota(unidade), json=corpo, headers=bearer(app, gestor))

    assert resposta.status_code == 201
    assert resposta.json()["no_cnes"] is False


async def test_servico_no_equipamento_da_unidade(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """006/R6.1: o serviço pode estar num equipamento da unidade, apontado pelo id."""
    unidade = await _unidade(sessoes)
    equipamento = await _equipamento(sessoes, unidade)
    gestor = await _gestor_da_unidade(sessoes, unidade)
    corpo = {**await _farmacia(sessoes), "equipamento_id": str(equipamento)}

    resposta = await cliente.post(_rota(unidade), json=corpo, headers=bearer(app, gestor))

    assert resposta.status_code == 201
    assert resposta.json()["equipamento_id"] == str(equipamento)
    [gravado] = await _gravados(sessoes)
    assert gravado["equipment_id"] == equipamento


@pytest.mark.parametrize("dono", ["outra-unidade", "sem-unidade", "inexistente"])
async def test_equipamento_que_nao_e_da_unidade_responde_422_e_nada_muda(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes, dono: str
) -> None:
    """006/R6.1: o equipamento do serviço tem de ser da mesma unidade."""
    unidade = await _unidade(sessoes)
    if dono == "outra-unidade":
        equipamento = await _equipamento(sessoes, await _unidade(sessoes, "CAPS Galdino Loreto"))
    elif dono == "sem-unidade":
        equipamento = await _equipamento(sessoes, None, nome="UTI móvel 01", tipo="UTI_MOVEL")
    else:
        equipamento = UUID("0197a000-0000-7000-8000-000000000001")
    gestor = await _gestor_da_unidade(sessoes, unidade)
    corpo = {**await _farmacia(sessoes), "equipamento_id": str(equipamento)}

    resposta = await cliente.post(_rota(unidade), json=corpo, headers=bearer(app, gestor))

    assert resposta.status_code == 422
    assert [erro["campo"] for erro in resposta.json()["errors"]] == ["equipamento_id"]
    assert await _gravados(sessoes) == []


async def test_lista_so_os_servicos_da_unidade(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """006/R6.1, 006/R6.3: com `unidade:read`, os serviços da unidade com `no_cnes`, sem os de
    outra nem os soltos."""
    unidade = await _unidade(sessoes)
    outra = await _unidade(sessoes, "CAPS Galdino Loreto")
    farmacia = await _servico(sessoes, unidade, no_cnes=True)
    vacina = await _servico(sessoes, unidade, nome="Sala de Vacina", tipo="SALA_VACINA")
    await _servico(sessoes, outra)
    await _servico(sessoes, None, nome="Sala de Vacinação do Shopping", tipo="SALA_VACINA")
    diretoria = await logado(sessoes, ("DIRETORIA", GLOBAL))

    resposta = await cliente.get(_rota(unidade), headers=bearer(app, diretoria))

    assert resposta.status_code == 200
    assert [(s["id"], s["nome"], s["no_cnes"]) for s in resposta.json()] == [
        (str(farmacia), "Farmácia do CAPS", True),
        (str(vacina), "Sala de Vacina", False),
    ]


async def test_listar_de_unidade_inexistente_responde_404(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """006/R6.1, 003/R4.3: com a permissão, unidade que não existe dá 404."""
    diretoria = await logado(sessoes, ("DIRETORIA", GLOBAL))

    resposta = await cliente.get(
        _rota(UUID("0197a000-0000-7000-8000-000000000001")), headers=bearer(app, diretoria)
    )

    assert resposta.status_code == 404


async def test_altera_so_os_campos_enviados_e_audita_o_que_mudou(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """006/R6.1, 006/R6.3: 200 com o serviço; `unidade.servico_atualizado` só com os campos
    que mudaram, inclusive o equipamento e o `no_cnes`."""
    unidade = await _unidade(sessoes)
    equipamento = await _equipamento(sessoes, unidade)
    servico = await _servico(sessoes, unidade)
    gestor = await _gestor_da_unidade(sessoes, unidade)

    resposta = await cliente.patch(
        _rota_do_servico(unidade, servico),
        json={"nome": "Farmácia do CAPS", "no_cnes": True, "equipamento_id": str(equipamento)},
        headers=bearer(app, gestor),
    )

    assert resposta.status_code == 200
    assert resposta.json()["no_cnes"] is True
    assert resposta.json()["equipamento_id"] == str(equipamento)
    [gravado] = await _gravados(sessoes)
    assert (gravado["in_cnes"], gravado["equipment_id"]) == (True, equipamento)
    [evento] = await eventos(sessoes, "unidade.servico_atualizado")
    assert (evento["entity_type"], evento["entity_id"]) == ("unidade", str(unidade))
    assert evento["changes"] == [
        {"campo": "servico.equipamento_id", "de": None, "para": str(equipamento)},
        {"campo": "servico.no_cnes", "de": False, "para": True},
    ]
    assert evento["metadata"] == {"servico_id": str(servico)}


async def test_equipamento_nulo_desliga_o_servico_do_equipamento(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """006/R6.1: `equipamento_id` nulo deixa o serviço só na unidade."""
    unidade = await _unidade(sessoes)
    equipamento = await _equipamento(sessoes, unidade)
    servico = await _servico(sessoes, unidade, equipamento=equipamento)
    gestor = await _gestor_da_unidade(sessoes, unidade)

    resposta = await cliente.patch(
        _rota_do_servico(unidade, servico),
        json={"equipamento_id": None},
        headers=bearer(app, gestor),
    )

    assert resposta.status_code == 200
    [gravado] = await _gravados(sessoes)
    assert (gravado["unit_id"], gravado["equipment_id"]) == (unidade, None)


async def test_alteracao_sem_mudanca_nao_audita(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """006/R6.1: nada mudou, nada a auditar (como a unidade, R3.6)."""
    unidade = await _unidade(sessoes)
    servico = await _servico(sessoes, unidade)
    gestor = await _gestor_da_unidade(sessoes, unidade)

    resposta = await cliente.patch(
        _rota_do_servico(unidade, servico), json={"status": "ativo"}, headers=bearer(app, gestor)
    )

    assert resposta.status_code == 200
    assert await eventos(sessoes, "unidade.servico_atualizado") == []


async def test_remove_servico_e_audita(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """006/R6.1: 204; o serviço sai do banco, e `unidade.servico_removido` leva os campos que
    ele tinha."""
    unidade = await _unidade(sessoes)
    servico = await _servico(sessoes, unidade)
    tipo = await _tipo(sessoes, "FARMACIA")
    gestor = await _gestor_da_unidade(sessoes, unidade)

    resposta = await cliente.delete(_rota_do_servico(unidade, servico), headers=bearer(app, gestor))

    assert resposta.status_code == 204
    assert await _gravados(sessoes) == []
    [evento] = await eventos(sessoes, "unidade.servico_removido")
    assert (evento["entity_type"], evento["entity_id"]) == ("unidade", str(unidade))
    assert evento["changes"] == [
        {"campo": "servico.tipo_servico_id", "de": tipo, "para": None},
        {"campo": "servico.equipamento_id", "de": None, "para": None},
        {"campo": "servico.nome", "de": "Farmácia do CAPS", "para": None},
        {"campo": "servico.no_cnes", "de": False, "para": None},
        {"campo": "servico.status", "de": "ativo", "para": None},
    ]
    assert evento["metadata"] == {"servico_id": str(servico)}


@pytest.mark.parametrize("metodo", ["PATCH", "DELETE"])
async def test_servico_de_outra_unidade_responde_404_e_nada_muda(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes, metodo: str
) -> None:
    """006/R6.1: o serviço é procurado só entre os da unidade da rota."""
    unidade = await _unidade(sessoes)
    outra = await _unidade(sessoes, "CAPS Galdino Loreto")
    servico = await _servico(sessoes, outra)
    gestor = await _gestor_da_unidade(sessoes, unidade)
    antes = await _gravados(sessoes)

    resposta = await cliente.request(
        metodo,
        _rota_do_servico(unidade, servico),
        json={"status": "inativo"} if metodo == "PATCH" else None,
        headers=bearer(app, gestor),
    )

    assert resposta.status_code == 404
    assert await _gravados(sessoes) == antes


async def _atribuicao(sessoes: Sessoes, papel: str) -> Atribuicao:
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
async def test_sem_servico_write_no_escopo_da_unidade_responde_403_e_nada_muda(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes, papel: str, metodo: str
) -> None:
    """006/R6.1, 003/R4.3, 003/R4.6: fora do escopo da unidade, ou sem a permissão, 403
    auditado com a unidade; nada muda."""
    unidade = await _unidade(sessoes)
    servico = await _servico(sessoes, unidade)
    usuario = await logado(sessoes, await _atribuicao(sessoes, papel))
    antes = await _gravados(sessoes)
    rota, molde = (
        (_rota(unidade), ROTA)
        if metodo == "POST"
        else (_rota_do_servico(unidade, servico), ROTA_DO_SERVICO)
    )

    resposta = await cliente.request(
        metodo,
        rota,
        json={"POST": await _farmacia(sessoes), "PATCH": {"status": "inativo"}}.get(metodo),
        headers=bearer(app, usuario),
    )

    assert resposta.status_code == 403
    [negacao] = await eventos(sessoes, "acesso.negado")
    assert (negacao["entity_type"], negacao["entity_id"]) == ("unidade", str(unidade))
    assert negacao["metadata"] == {"permissao": "servico:write", "rota": f"{metodo} {molde}"}
    assert await _gravados(sessoes) == antes


@pytest.mark.parametrize(
    "papel", ["COORD_TECNICO", "TECNICO_DISTRITAL", "GESTOR_UNIDADE", "GESTOR_DADOS"]
)
async def test_quem_tem_servico_write_no_escopo_da_unidade_adiciona(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes, papel: str
) -> None:
    """006/R6.1: `servico:write` na área, no distrito, na unidade ou global basta."""
    unidade = await _unidade(sessoes)
    escopos = {
        "COORD_TECNICO": ("area", str(await id_pelo_codigo(sessoes, "area", "SAUDE_MENTAL"))),
        "TECNICO_DISTRITAL": ("distrito", str(await id_pelo_codigo(sessoes, "distrito", "DS-I"))),
        "GESTOR_UNIDADE": ("unidade", str(unidade)),
    }
    usuario = await logado(sessoes, (papel, escopos.get(papel, GLOBAL)))

    resposta = await cliente.post(
        _rota(unidade), json=await _farmacia(sessoes), headers=bearer(app, usuario)
    )

    assert resposta.status_code == 201


@pytest.mark.parametrize("tipo", ["inexistente", "desativado"])
@pytest.mark.parametrize("metodo", ["POST", "PATCH"])
async def test_tipo_inexistente_ou_desativado_responde_422_e_nada_muda(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes, tipo: str, metodo: str
) -> None:
    """006/R6.1: o tipo de serviço tem de existir e estar ativo, como as referências da unidade
    (R1.2)."""
    async with sessoes() as sessao, sessao.begin():
        await sessao.execute(
            text("UPDATE service_types SET is_active = false WHERE code = 'ESPACO_MAE_CORUJA'")
        )
    tipo_id = 32000 if tipo == "inexistente" else await _tipo(sessoes, "ESPACO_MAE_CORUJA")
    unidade = await _unidade(sessoes)
    servico = await _servico(sessoes, unidade)
    gestor = await _gestor_da_unidade(sessoes, unidade)
    antes = await _gravados(sessoes)

    if metodo == "POST":
        resposta = await cliente.post(
            _rota(unidade),
            json={**await _farmacia(sessoes), "tipo_servico_id": tipo_id},
            headers=bearer(app, gestor),
        )
    else:
        resposta = await cliente.patch(
            _rota_do_servico(unidade, servico),
            json={"tipo_servico_id": tipo_id},
            headers=bearer(app, gestor),
        )

    assert resposta.status_code == 422
    assert [erro["campo"] for erro in resposta.json()["errors"]] == ["tipo_servico_id"]
    assert await _gravados(sessoes) == antes


@pytest.mark.parametrize(
    ("alteracao", "campo"),
    [
        ({"nome": ""}, "nome"),
        ({"tipo_servico_id": 0}, "tipo_servico_id"),
        ({"no_cnes": "talvez"}, "no_cnes"),
        ({"status": "quebrado"}, "status"),
        ({"status": None}, "status"),
        ({"unidade_id": None}, "unidade_id"),
    ],
    ids=["nome-vazio", "tipo-zero", "no-cnes-invalido", "status-invalido", "sem-status", "extra"],
)
async def test_corpo_invalido_responde_422(
    app: FastAPI,
    cliente: httpx.AsyncClient,
    sessoes: Sessoes,
    alteracao: dict[str, Any],
    campo: str,
) -> None:
    """006/R6.1: formato conferido no schema; nada é gravado."""
    unidade = await _unidade(sessoes)
    gestor = await _gestor_da_unidade(sessoes, unidade)
    corpo = {**await _farmacia(sessoes), **alteracao}
    if alteracao == {"status": None}:
        del corpo["status"]

    resposta = await cliente.post(_rota(unidade), json=corpo, headers=bearer(app, gestor))

    assert resposta.status_code == 422
    assert [erro["campo"] for erro in resposta.json()["errors"]] == [campo]
    assert await _gravados(sessoes) == []


@pytest.mark.parametrize("campo", ["nome", "tipo_servico_id", "no_cnes", "status"])
async def test_patch_com_obrigatorio_nulo_responde_422(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes, campo: str
) -> None:
    """006/R6.1: no PATCH, o que tem valor sempre pode faltar, mas não vir nulo."""
    unidade = await _unidade(sessoes)
    servico = await _servico(sessoes, unidade)
    gestor = await _gestor_da_unidade(sessoes, unidade)

    resposta = await cliente.patch(
        _rota_do_servico(unidade, servico), json={campo: None}, headers=bearer(app, gestor)
    )

    assert resposta.status_code == 422
    assert [erro["campo"] for erro in resposta.json()["errors"]] == [campo]


@pytest.mark.parametrize(
    ("metodo", "rota"),
    [("GET", ROTA), ("POST", ROTA), ("PATCH", ROTA_DO_SERVICO), ("DELETE", ROTA_DO_SERVICO)],
)
async def test_sem_bearer_responde_401(
    cliente: httpx.AsyncClient, sessoes: Sessoes, metodo: str, rota: str
) -> None:
    """003/R4.1: as rotas exigem autenticação; nada muda."""
    unidade = await _unidade(sessoes)
    servico = await _servico(sessoes, unidade)
    antes = await _gravados(sessoes)

    resposta = await cliente.request(
        metodo,
        rota.format(id=unidade, sid=servico),
        json={"POST": await _farmacia(sessoes), "PATCH": {"status": "inativo"}}.get(metodo),
    )

    assert resposta.status_code == 401
    assert await _gravados(sessoes) == antes


# --- Vínculo pelo id (R6.4) -----------------------------------------------------------------


async def test_renomear_a_unidade_reflete_nos_servicos_sem_editar_o_servico(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """006/R6.4: o serviço aponta a unidade pelo id; renomeada a unidade, o serviço continua
    nela, com o nome novo, e não é tocado nem auditado."""
    unidade = await _unidade(sessoes)
    servico = await _servico(sessoes, unidade)
    antes = await _gravados(sessoes)
    gestor_de_dados = await logado(sessoes, ("GESTOR_DADOS", GLOBAL))
    cabecalhos = bearer(app, gestor_de_dados)

    renomeada = await cliente.patch(
        f"/api/v1/unidades/{unidade}",
        json={"nome": "Policlínica Lessa de Andrade (Madalena)"},
        headers={**cabecalhos, "If-Match": '"1"'},
    )

    assert renomeada.status_code == 200
    assert await _gravados(sessoes) == antes
    assert await eventos(sessoes, "unidade.servico_atualizado") == []
    listagem = await cliente.get(_rota(unidade), headers=cabecalhos)
    assert [(s["id"], s["unidade_id"]) for s in listagem.json()] == [(str(servico), str(unidade))]
    detalhe = (await cliente.get(f"/api/v1/unidades/{unidade}", headers=cabecalhos)).json()
    assert detalhe["nome"] == "Policlínica Lessa de Andrade (Madalena)"
    assert [s["id"] for s in detalhe["servicos"]] == [str(servico)]


# --- Serviços soltos (R6.2) -----------------------------------------------------------------


async def test_gestor_de_dados_cadastra_servico_solto_auditado(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """006/R6.2, 006/R6.3: 201 com `unidade_id` nulo; `servico.criado` com o próprio serviço
    como entidade, porque não há unidade."""
    gestor = await logado(sessoes, ("GESTOR_DADOS", GLOBAL))
    vacina = await _tipo(sessoes, "SALA_VACINA")
    corpo = {"nome": "Sala de Vacinação do Shopping", "tipo_servico_id": vacina, "status": "ativo"}

    resposta = await cliente.post(ROTA_SOLTOS, json=corpo, headers=bearer(app, gestor))

    assert resposta.status_code == 201
    servico = resposta.json()["id"]
    assert (resposta.json()["unidade_id"], resposta.json()["no_cnes"]) == (None, False)
    [gravado] = await _gravados(sessoes)
    assert (gravado["unit_id"], gravado["equipment_id"], gravado["name"]) == (
        None,
        None,
        "Sala de Vacinação do Shopping",
    )
    assert await eventos(sessoes, "servico.criado") == [
        {
            "actor_user_id": gestor.user_id,
            "session_id": gestor.id,
            "entity_type": "servico",
            "entity_id": servico,
            "changes": [
                {"campo": "tipo_servico_id", "de": None, "para": vacina},
                {"campo": "equipamento_id", "de": None, "para": None},
                {"campo": "nome", "de": None, "para": "Sala de Vacinação do Shopping"},
                {"campo": "no_cnes", "de": None, "para": False},
                {"campo": "status", "de": None, "para": "ativo"},
            ],
            "metadata": {},
        }
    ]


async def test_servico_solto_pode_estar_em_equipamento_sem_unidade(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """006/R6.2: sem unidade, o equipamento do serviço também é sem unidade (a UTI móvel)."""
    uti = await _equipamento(sessoes, None, nome="UTI móvel 01", tipo="UTI_MOVEL")
    gestor = await logado(sessoes, ("GESTOR_DADOS", GLOBAL))
    corpo = {**await _farmacia(sessoes), "equipamento_id": str(uti)}

    resposta = await cliente.post(ROTA_SOLTOS, json=corpo, headers=bearer(app, gestor))

    assert resposta.status_code == 201
    assert resposta.json()["equipamento_id"] == str(uti)


async def test_servico_solto_em_equipamento_de_unidade_responde_422(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """006/R6.2: o serviço solto não entra em equipamento de unidade."""
    equipamento = await _equipamento(sessoes, await _unidade(sessoes))
    gestor = await logado(sessoes, ("GESTOR_DADOS", GLOBAL))
    corpo = {**await _farmacia(sessoes), "equipamento_id": str(equipamento)}

    resposta = await cliente.post(ROTA_SOLTOS, json=corpo, headers=bearer(app, gestor))

    assert resposta.status_code == 422
    assert [erro["campo"] for erro in resposta.json()["errors"]] == ["equipamento_id"]
    assert await _gravados(sessoes) == []


async def test_gestor_de_dados_lista_so_os_servicos_soltos(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """006/R6.2: `GET /servicos` traz os serviços sem unidade."""
    await _servico(sessoes, await _unidade(sessoes))
    solto = await _servico(sessoes, None, nome="Sala de Vacinação do Shopping")
    gestor = await logado(sessoes, ("GESTOR_DADOS", GLOBAL))

    resposta = await cliente.get(ROTA_SOLTOS, headers=bearer(app, gestor))

    assert resposta.status_code == 200
    assert [(s["id"], s["unidade_id"]) for s in resposta.json()] == [(str(solto), None)]


@pytest.mark.parametrize(
    "papel",
    ["COORD_TECNICO", "TECNICO_DISTRITAL", "GESTOR_UNIDADE", "DIRETORIA", "AUDITOR", "ADMIN_TI"],
)
@pytest.mark.parametrize("metodo", ["GET", "POST"])
async def test_so_gestor_de_dados_usa_servicos_soltos(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes, papel: str, metodo: str
) -> None:
    """006/R6.2, 003/R4.6: `servico:write` com escopo de área, distrito ou unidade não basta;
    403 auditado, sem entidade, e nada é gravado."""
    unidade = await _unidade(sessoes)
    escopos = {
        "COORD_TECNICO": ("area", str(await id_pelo_codigo(sessoes, "area", "SAUDE_MENTAL"))),
        "TECNICO_DISTRITAL": ("distrito", str(await id_pelo_codigo(sessoes, "distrito", "DS-I"))),
        "GESTOR_UNIDADE": ("unidade", str(unidade)),
    }
    usuario = await logado(sessoes, (papel, escopos.get(papel, GLOBAL)))

    resposta = await cliente.request(
        metodo,
        ROTA_SOLTOS,
        json=await _farmacia(sessoes) if metodo == "POST" else None,
        headers=bearer(app, usuario),
    )

    assert resposta.status_code == 403
    [negacao] = await eventos(sessoes, "acesso.negado")
    assert negacao["entity_type"] is None
    assert negacao["metadata"] == {"permissao": "servico:write", "rota": f"{metodo} {ROTA_SOLTOS}"}
    assert await _gravados(sessoes) == []
    assert await eventos(sessoes, "servico.criado") == []


@pytest.mark.parametrize("metodo", ["GET", "POST"])
async def test_servicos_soltos_sem_bearer_responde_401(
    cliente: httpx.AsyncClient, metodo: str
) -> None:
    """003/R4.1: a rota exige autenticação."""
    resposta = await cliente.request(metodo, ROTA_SOLTOS, json={"nome": "x"})

    assert resposta.status_code == 401
