"""`POST /api/v1/unidades`: criar unidade com unicidade e auditoria (006/T3).

Design da 006 § Rotas e § Schemas; matriz da arquitetura-conceitual.md § 4 (`unidade:create`:
`GESTOR_DADOS` global, `COORD_TECNICO` na sua área técnica).
"""

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.core.ids import uuid7
from src.main import create_app
from src.modules.identity.domain.sessions import AuthSession
from tests.factories import make_settings
from tests.integration.acesso import GLOBAL, Sessoes, bearer, eventos, id_pelo_codigo, logado
from tests.integration.postgres import BancoDeTeste, motor

ROTA = "/api/v1/unidades"


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


async def _corpo(sessoes: Sessoes, **campos: Any) -> dict[str, Any]:
    """Unidade válida com só os campos obrigatórios (006/R1.2), CAPS II no DS I."""
    corpo: dict[str, Any] = {
        "nome": "CAPS Espaço Azul",
        "tipo_unidade_id": await id_pelo_codigo(sessoes, "tipo_unidade", "CAPS_II"),
        "distrito_id": await id_pelo_codigo(sessoes, "distrito", "DS-I"),
        "cep": "50010100",
        "endereco": "Rua do Sol, 150",
        "status": "ativa",
    }
    return corpo | campos


async def test_gestor_de_dados_cria_unidade_e_recebe_201_com_o_recurso_completo(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """006/R1.1, 006/R1.2: `GESTOR_DADOS` (global) cria; a resposta traz a unidade inteira."""
    gestor = await logado(sessoes, ("GESTOR_DADOS", GLOBAL))
    corpo = await _corpo(
        sessoes,
        cnes="2345678",
        cep="50010-100",
        bairro="Boa Vista",
        telefone="(81) 3355-0000",
        nome_gestor="Ana Souza",
        latitude=-8.063169,
        longitude=-34.871139,
        status="em_implantacao",
    )

    resposta = await cliente.post(ROTA, json=corpo, headers=bearer(app, gestor))

    assert resposta.status_code == 201
    unidade = resposta.json()
    assert unidade.keys() == {
        "id",
        "nome",
        "cnes",
        "cnes_pendente",
        "tipo_unidade_id",
        "distrito_id",
        "cep",
        "endereco",
        "bairro",
        "telefone",
        "nome_gestor",
        "horario_funcionamento",
        "latitude",
        "longitude",
        "status",
        "pendencias",
        "versao",
        "criado_em",
        "atualizado_em",
    }
    assert {campo: unidade[campo] for campo in corpo} == corpo | {"cep": "50010100"}
    assert unidade["cnes_pendente"] is False
    assert unidade["horario_funcionamento"] is None
    assert unidade["pendencias"] == 0
    assert unidade["versao"] == 1
    assert resposta.headers["location"] == f"{ROTA}/{unidade['id']}"
    assert resposta.headers["etag"] == '"1"'


async def test_criacao_audita_unidade_criada_com_todos_os_campos(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """006/R1.6: `unidade.criada` com cada campo da unidade (`de` nulo), na mesma transação."""
    gestor = await logado(sessoes, ("GESTOR_DADOS", GLOBAL))
    corpo = await _corpo(sessoes, cnes="2345678", nome_gestor="Ana Souza", latitude=-8.063169)

    resposta = await cliente.post(ROTA, json=corpo, headers=bearer(app, gestor))

    assert resposta.status_code == 201
    unidade = resposta.json()
    assert await eventos(sessoes, "unidade.criada") == [
        {
            "actor_user_id": gestor.user_id,
            "session_id": gestor.id,
            "entity_type": "unidade",
            "entity_id": unidade["id"],
            "changes": [
                {"campo": "name", "de": None, "para": "CAPS Espaço Azul"},
                {"campo": "unit_type_id", "de": None, "para": corpo["tipo_unidade_id"]},
                {"campo": "district_id", "de": None, "para": corpo["distrito_id"]},
                {"campo": "cep", "de": None, "para": "50010100"},
                {"campo": "address", "de": None, "para": "Rua do Sol, 150"},
                {"campo": "status", "de": None, "para": "ativa"},
                {"campo": "cnes", "de": None, "para": "2345678"},
                {"campo": "neighborhood", "de": None, "para": None},
                {"campo": "phone", "de": None, "para": None},
                {"campo": "manager_name", "de": None, "para": "Ana Souza"},
                {"campo": "opening_hours", "de": None, "para": None},
                {"campo": "latitude", "de": None, "para": -8.063169},
                {"campo": "longitude", "de": None, "para": None},
            ],
            "metadata": {},
        }
    ]


async def test_unidade_sem_cnes_e_aceita_e_fica_com_cnes_pendente(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """006/R1.5: serviço municipal fora do CNES; duas unidades sem CNES não conflitam."""
    gestor = await logado(sessoes, ("GESTOR_DADOS", GLOBAL))

    primeira = await cliente.post(ROTA, json=await _corpo(sessoes), headers=bearer(app, gestor))
    segunda = await cliente.post(
        ROTA, json=await _corpo(sessoes, nome="CAPS Vila Azul"), headers=bearer(app, gestor)
    )

    assert (primeira.status_code, segunda.status_code) == (201, 201)
    assert primeira.json()["cnes"] is None
    assert primeira.json()["cnes_pendente"] is True


async def test_cnes_repetido_responde_409_indicando_a_unidade_existente(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """006/R1.3: mesmo CNES em outro nome e distrito; nada é gravado nem auditado."""
    gestor = await logado(sessoes, ("GESTOR_DADOS", GLOBAL))
    existente = await cliente.post(
        ROTA, json=await _corpo(sessoes, cnes="2345678"), headers=bearer(app, gestor)
    )
    outro_distrito = await id_pelo_codigo(sessoes, "distrito", "DS-IV")

    resposta = await cliente.post(
        ROTA,
        json=await _corpo(sessoes, cnes="2345678", nome="Outro CAPS", distrito_id=outro_distrito),
        headers=bearer(app, gestor),
    )

    assert resposta.status_code == 409
    assert resposta.headers["content-type"] == "application/problem+json"
    problema = resposta.json()
    assert problema["title"] == "Conflito"
    assert problema["detail"] == "Já existe uma unidade com este CNES."
    assert problema["unidade_existente_id"] == existente.json()["id"]
    assert len(await eventos(sessoes, "unidade.criada")) == 1


async def test_nome_normalizado_repetido_no_mesmo_distrito_responde_409(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """006/R1.4: sem acento, caixa e espaços extras, "  ESPACO   azul " é "Espaço Azul"."""
    gestor = await logado(sessoes, ("GESTOR_DADOS", GLOBAL))
    existente = await cliente.post(
        ROTA, json=await _corpo(sessoes, nome="Espaço Azul"), headers=bearer(app, gestor)
    )

    resposta = await cliente.post(
        ROTA, json=await _corpo(sessoes, nome="  ESPACO   azul "), headers=bearer(app, gestor)
    )

    assert resposta.status_code == 409
    assert resposta.json()["detail"] == "Já existe uma unidade com este nome no distrito."
    assert resposta.json()["unidade_existente_id"] == existente.json()["id"]
    assert len(await eventos(sessoes, "unidade.criada")) == 1


async def test_mesmo_nome_em_outro_distrito_e_aceito(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """006/R1.4: a unicidade do nome vale dentro do distrito."""
    gestor = await logado(sessoes, ("GESTOR_DADOS", GLOBAL))
    outro_distrito = await id_pelo_codigo(sessoes, "distrito", "DS-II")
    await cliente.post(ROTA, json=await _corpo(sessoes), headers=bearer(app, gestor))

    resposta = await cliente.post(
        ROTA, json=await _corpo(sessoes, distrito_id=outro_distrito), headers=bearer(app, gestor)
    )

    assert resposta.status_code == 201


async def test_duas_criacoes_simultaneas_da_mesma_unidade_dao_201_e_409(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """006/R1.3: a que perde a corrida recebe 409, e não 500 por violar o índice único."""
    gestor = await logado(sessoes, ("GESTOR_DADOS", GLOBAL))
    corpo = await _corpo(sessoes, cnes="2345678")

    respostas = await asyncio.gather(
        *(cliente.post(ROTA, json=corpo, headers=bearer(app, gestor)) for _ in range(2))
    )

    assert sorted(resposta.status_code for resposta in respostas) == [201, 409]
    assert len(await eventos(sessoes, "unidade.criada")) == 1


async def _coordenador_de_saude_mental(sessoes: Sessoes) -> AuthSession:
    area = await id_pelo_codigo(sessoes, "area", "SAUDE_MENTAL")
    return await logado(sessoes, ("COORD_TECNICO", ("area", str(area))))


async def test_coordenador_tecnico_cria_unidade_de_tipo_da_sua_area(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """006/R1.1: `unidade:create` no escopo da área técnica do tipo (CAPS II é Saúde Mental)."""
    coordenador = await _coordenador_de_saude_mental(sessoes)

    resposta = await cliente.post(
        ROTA, json=await _corpo(sessoes), headers=bearer(app, coordenador)
    )

    assert resposta.status_code == 201


async def test_coordenador_tecnico_nao_cria_unidade_de_tipo_de_outra_area(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """006/R1.1, 003/R4.6: USF é da APS; 403 auditado como `acesso.negado`, nada gravado."""
    coordenador = await _coordenador_de_saude_mental(sessoes)
    corpo = await _corpo(
        sessoes,
        cnes="2345678",
        tipo_unidade_id=await id_pelo_codigo(sessoes, "tipo_unidade", "USF"),
    )

    resposta = await cliente.post(ROTA, json=corpo, headers=bearer(app, coordenador))

    assert resposta.status_code == 403
    assert resposta.json()["title"] == "Acesso negado"
    assert await eventos(sessoes, "acesso.negado") == [
        {
            "actor_user_id": coordenador.user_id,
            "session_id": coordenador.id,
            "entity_type": None,
            "entity_id": None,
            "changes": [],
            "metadata": {"permissao": "unidade:create", "rota": "POST /api/v1/unidades"},
        }
    ]
    assert await eventos(sessoes, "unidade.criada") == []
    # Nada ficou gravado: a mesma unidade, pelo Gestor de Dados, não conflita.
    gestor = await logado(sessoes, ("GESTOR_DADOS", GLOBAL))
    assert (await cliente.post(ROTA, json=corpo, headers=bearer(app, gestor))).status_code == 201


@pytest.mark.parametrize(
    ("desativar", "campos", "esperado"),
    [
        (None, {"tipo_unidade_id": 32000}, ["tipo_unidade_id"]),
        (None, {"distrito_id": 32000}, ["distrito_id"]),
        (
            None,
            {"tipo_unidade_id": 32000, "distrito_id": 32000},
            ["tipo_unidade_id", "distrito_id"],
        ),
        ("UPDATE unit_types SET is_active = false WHERE code = 'CAPS_II'", {}, ["tipo_unidade_id"]),
        ("UPDATE districts SET is_active = false WHERE code = 'DS-I'", {}, ["distrito_id"]),
    ],
    ids=[
        "tipo-inexistente",
        "distrito-inexistente",
        "os-dois",
        "tipo-desativado",
        "distrito-desativado",
    ],
)
async def test_tipo_ou_distrito_inexistente_ou_desativado_responde_422(
    app: FastAPI,
    cliente: httpx.AsyncClient,
    sessoes: Sessoes,
    banco: BancoDeTeste,
    desativar: str | None,
    campos: dict[str, Any],
    esperado: list[str],
) -> None:
    """006/R1.2: o tipo e o distrito têm de existir e estar ativos (exclusão lógica, 006/R7.2)."""
    gestor = await logado(sessoes, ("GESTOR_DADOS", GLOBAL))
    corpo = await _corpo(sessoes, **campos)
    if desativar is not None:
        dono = motor(banco.url_dono)
        async with dono.begin() as conexao:
            await conexao.execute(text(desativar))
        await dono.dispose()

    resposta = await cliente.post(ROTA, json=corpo, headers=bearer(app, gestor))

    assert resposta.status_code == 422
    assert [erro["campo"] for erro in resposta.json()["errors"]] == esperado
    assert await eventos(sessoes, "unidade.criada") == []


@pytest.mark.parametrize(
    "campo", ["nome", "tipo_unidade_id", "distrito_id", "cep", "endereco", "status"]
)
async def test_campo_obrigatorio_ausente_responde_422(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes, campo: str
) -> None:
    """006/R1.2: nome, tipo, distrito, endereço com CEP e status são obrigatórios."""
    gestor = await logado(sessoes, ("GESTOR_DADOS", GLOBAL))
    corpo = await _corpo(sessoes)
    del corpo[campo]

    resposta = await cliente.post(ROTA, json=corpo, headers=bearer(app, gestor))

    assert resposta.status_code == 422
    assert resposta.json()["errors"] == [{"campo": campo, "mensagem": "Campo obrigatório."}]


@pytest.mark.parametrize(
    ("campos", "campo"),
    [
        ({"nome": "   "}, "nome"),
        ({"nome": "x" * 201}, "nome"),
        ({"cnes": "234567"}, "cnes"),
        ({"cnes": "23456789"}, "cnes"),
        ({"cnes": "234567a"}, "cnes"),
        ({"cep": "5001010"}, "cep"),
        ({"cep": "50.010-100"}, "cep"),
        ({"cep": "".join(chr(0xFF10 + int(d)) for d in "50010100")}, "cep"),  # dígitos largos
        ({"status": "suspensa"}, "status"),
        ({"telefone": "ligue já"}, "telefone"),
        ({"latitude": 91}, "latitude"),
        ({"longitude": -34.1234567}, "longitude"),
        ({"versao": 7}, "versao"),
        ({"pendencias": 0}, "pendencias"),
    ],
    ids=[
        "nome-vazio",
        "nome-longo",
        "cnes-curto",
        "cnes-longo",
        "cnes-letra",
        "cep-curto",
        "cep-pontuado",
        "cep-digitos-largos",
        "status-desconhecido",
        "telefone-texto",
        "latitude-fora",
        "longitude-7-casas",
        "versao-nao-se-envia",
        "pendencias-nao-se-envia",
    ],
)
async def test_formato_invalido_responde_422(
    app: FastAPI,
    cliente: httpx.AsyncClient,
    sessoes: Sessoes,
    campos: dict[str, Any],
    campo: str,
) -> None:
    """006/R1.2 e design § Schemas: o formato é conferido no schema, antes do caso de uso."""
    gestor = await logado(sessoes, ("GESTOR_DADOS", GLOBAL))

    resposta = await cliente.post(
        ROTA, json=await _corpo(sessoes, **campos), headers=bearer(app, gestor)
    )

    assert resposta.status_code == 422
    assert [erro["campo"] for erro in resposta.json()["errors"]] == [campo]


async def test_sem_bearer_responde_401(cliente: httpx.AsyncClient, sessoes: Sessoes) -> None:
    """003/R4.1: a rota exige autenticação."""
    resposta = await cliente.post(ROTA, json=await _corpo(sessoes))

    assert resposta.status_code == 401
    assert resposta.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize("papel", ["TECNICO_DISTRITAL", "GESTOR_UNIDADE", "DIRETORIA", "ADMIN_TI"])
async def test_papel_sem_unidade_create_responde_403(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes, papel: str
) -> None:
    """006/R1.1, 003/R4.2: só `GESTOR_DADOS` e `COORD_TECNICO` têm `unidade:create` (matriz § 4)."""
    escopos = {
        "TECNICO_DISTRITAL": ("distrito", str(await id_pelo_codigo(sessoes, "distrito", "DS-I"))),
        "GESTOR_UNIDADE": ("unidade", str(uuid7())),
    }
    usuario = await logado(sessoes, (papel, escopos.get(papel, GLOBAL)))

    resposta = await cliente.post(ROTA, json=await _corpo(sessoes), headers=bearer(app, usuario))

    assert resposta.status_code == 403
    assert len(await eventos(sessoes, "acesso.negado")) == 1
    assert await eventos(sessoes, "unidade.criada") == []
