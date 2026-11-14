"""Rotas das tabelas de referência (006/T9; design da 006 § Rotas).

`GET /api/v1/referencias/*` para qualquer usuário autenticado (R7.1); `POST` e `PATCH` só com
`regra_validacao:manage`, que a matriz (arquitetura-conceitual.md § 4) dá ao `GESTOR_DADOS`,
global (R7.2). A correção do código de tipo de equipamento, com a cascata, está em
`test_referencia_codigo.py` (011/T18, R7.3).
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

BASE = "/api/v1/referencias"
TABELAS = ["distritos", "areas-tecnicas", "tipos-unidade", "tipos-equipamento", "tipos-servico"]


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


async def _id(sessoes: Sessoes, tabela: str, codigo: str) -> int:
    async with sessoes() as sessao:
        id_ = await sessao.scalar(
            text(f"SELECT id FROM {tabela} WHERE code = :codigo"),  # noqa: S608 (tabela fixa)
            {"codigo": codigo},
        )
    assert id_ is not None
    return int(id_)


# --- Leitura (R7.1) ---


async def test_usuario_sem_papel_le_as_referencias_semeadas(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """006/R7.1: basta estar autenticado; os itens vêm com id, código, nome e `ativo`, e o tipo
    de unidade traz a área técnica."""
    usuario = await logado(sessoes)
    cabecalhos = bearer(app, usuario)

    distritos = await cliente.get(f"{BASE}/distritos", headers=cabecalhos)
    tipos_equipamento = await cliente.get(f"{BASE}/tipos-equipamento", headers=cabecalhos)
    tipos_unidade = await cliente.get(f"{BASE}/tipos-unidade", headers=cabecalhos)
    areas = await cliente.get(f"{BASE}/areas-tecnicas", headers=cabecalhos)
    tipos_servico = await cliente.get(f"{BASE}/tipos-servico", headers=cabecalhos)

    assert distritos.status_code == 200
    assert [d["codigo"] for d in distritos.json()][:2] == ["DS-I", "DS-II"]
    assert [(t["codigo"], t["nome"], t["ativo"]) for t in tipos_equipamento.json()] == [
        ("UTI_MOVEL", "UTI móvel", True),
        ("MATERNIDADE", "Maternidade", True),
        ("POLICLINICA", "Policlínica", True),
    ]
    caps = tipos_unidade.json()[0]
    assert caps["codigo"] == "CAPS_II"
    assert caps["area_tecnica_id"] == await id_pelo_codigo(sessoes, "area", "SAUDE_MENTAL")
    assert [a["codigo"] for a in areas.json()] == ["SAUDE_MENTAL", "SAUDE_BUCAL", "APS", "MAC"]
    assert "FARMACIA" in [s["codigo"] for s in tipos_servico.json()]
    assert set(tipos_servico.json()[0]) == {"id", "codigo", "nome", "ativo"}


@pytest.mark.parametrize("tabela", TABELAS)
async def test_sem_bearer_responde_401(cliente: httpx.AsyncClient, tabela: str) -> None:
    """003/R4.1: a leitura exige autenticação."""
    resposta = await cliente.get(f"{BASE}/{tabela}")

    assert resposta.status_code == 401


# --- Inclusão (R7.2) ---


async def test_gestor_de_dados_inclui_item_com_auditoria(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """006/R7.2: o item nasce ativo, aparece na lista e `referencia.criada` traz os campos."""
    gestor = await logado(sessoes, ("GESTOR_DADOS", GLOBAL))

    resposta = await cliente.post(
        f"{BASE}/tipos-servico",
        json={"codigo": " ACADEMIA_SAUDE ", "nome": "Academia da Saúde"},
        headers=bearer(app, gestor),
    )

    assert resposta.status_code == 201
    criado = resposta.json()
    assert criado == {
        "id": criado["id"],
        "codigo": "ACADEMIA_SAUDE",
        "nome": "Academia da Saúde",
        "ativo": True,
    }
    lista = await cliente.get(f"{BASE}/tipos-servico", headers=bearer(app, gestor))
    assert criado in lista.json()
    [evento] = await eventos(sessoes, "referencia.criada")
    assert evento["actor_user_id"] == gestor.user_id
    assert evento["entity_type"] == "tipo_servico"
    assert evento["entity_id"] == str(criado["id"])
    assert evento["changes"] == [
        {"campo": "codigo", "de": None, "para": "ACADEMIA_SAUDE"},
        {"campo": "nome", "de": None, "para": "Academia da Saúde"},
        {"campo": "ativo", "de": None, "para": True},
    ]


async def test_tipo_de_unidade_novo_aponta_area_tecnica_ativa(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """006/R7.2: o tipo de unidade pede a área técnica; área inexistente → 422 no campo."""
    gestor = await logado(sessoes, ("GESTOR_DADOS", GLOBAL))
    aps = await id_pelo_codigo(sessoes, "area", "APS")

    criado = await cliente.post(
        f"{BASE}/tipos-unidade",
        json={"codigo": "UBS", "nome": "Unidade Básica de Saúde", "area_tecnica_id": aps},
        headers=bearer(app, gestor),
    )
    sem_area = await cliente.post(
        f"{BASE}/tipos-unidade",
        json={"codigo": "UPA", "nome": "UPA", "area_tecnica_id": 32000},
        headers=bearer(app, gestor),
    )

    assert criado.status_code == 201
    assert criado.json()["area_tecnica_id"] == aps
    assert sem_area.status_code == 422
    assert [e["campo"] for e in sem_area.json()["errors"]] == ["area_tecnica_id"]


async def test_codigo_repetido_na_inclusao_responde_409(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """006/R7.2: o código é único na tabela; nada é gravado nem auditado."""
    gestor = await logado(sessoes, ("GESTOR_DADOS", GLOBAL))

    resposta = await cliente.post(
        f"{BASE}/distritos", json={"codigo": "DS-I", "nome": "Outro"}, headers=bearer(app, gestor)
    )

    assert resposta.status_code == 409
    assert await eventos(sessoes, "referencia.criada") == []


@pytest.mark.parametrize(
    "corpo",
    [{}, {"codigo": "", "nome": "X"}, {"codigo": "X" * 21, "nome": "X"}, {"codigo": "X"}],
    ids=["vazio", "codigo-vazio", "codigo-longo-para-distrito", "sem-nome"],
)
async def test_inclusao_com_campos_invalidos_responde_422(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes, corpo: dict[str, object]
) -> None:
    """006/R7.2: código e nome obrigatórios, nos tamanhos das colunas."""
    gestor = await logado(sessoes, ("GESTOR_DADOS", GLOBAL))

    resposta = await cliente.post(f"{BASE}/distritos", json=corpo, headers=bearer(app, gestor))

    assert resposta.status_code == 422


# --- Alteração e desativação (R7.2) ---


async def test_gestor_de_dados_altera_codigo_e_nome_com_auditoria(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """006/R7.2: o código também é editável; `referencia.atualizada` traz só o que mudou (o
    `ativo` enviado igual não entra)."""
    gestor = await logado(sessoes, ("GESTOR_DADOS", GLOBAL))
    distrito = await _id(sessoes, "districts", "DS-VIII")

    resposta = await cliente.patch(
        f"{BASE}/distritos/{distrito}",
        json={"codigo": "DS-8", "nome": "Distrito Sanitário 8", "ativo": True},
        headers=bearer(app, gestor),
    )

    assert resposta.status_code == 200
    assert resposta.json()["codigo"] == "DS-8"
    [evento] = await eventos(sessoes, "referencia.atualizada")
    assert evento["entity_type"] == "distrito"
    assert evento["entity_id"] == str(distrito)
    assert evento["changes"][0] == {"campo": "codigo", "de": "DS-VIII", "para": "DS-8"}
    assert [m["campo"] for m in evento["changes"]] == ["codigo", "nome"]
    assert evento["metadata"] == {}


async def test_desativar_mantem_o_item_na_lista_como_inativo(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """006/R7.2: desativar é `ativo: false` (exclusão lógica); o item continua listado."""
    gestor = await logado(sessoes, ("GESTOR_DADOS", GLOBAL))
    farmacia = await _id(sessoes, "service_types", "FARMACIA")

    resposta = await cliente.patch(
        f"{BASE}/tipos-servico/{farmacia}", json={"ativo": False}, headers=bearer(app, gestor)
    )

    assert resposta.status_code == 200
    assert resposta.json()["ativo"] is False
    lista = (await cliente.get(f"{BASE}/tipos-servico", headers=bearer(app, gestor))).json()
    assert {"id": farmacia, "codigo": "FARMACIA"}.items() <= next(
        s for s in lista if s["id"] == farmacia
    ).items()
    assert next(s for s in lista if s["id"] == farmacia)["ativo"] is False
    [evento] = await eventos(sessoes, "referencia.atualizada")
    assert evento["changes"] == [{"campo": "ativo", "de": True, "para": False}]


async def test_trocar_a_area_do_tipo_de_unidade(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """006/R7.2: a área técnica do tipo é editável e auditada; área inexistente → 422."""
    gestor = await logado(sessoes, ("GESTOR_DADOS", GLOBAL))
    tipo = await id_pelo_codigo(sessoes, "tipo_unidade", "POLICLINICA")
    mental = await id_pelo_codigo(sessoes, "area", "SAUDE_MENTAL")
    mac = await id_pelo_codigo(sessoes, "area", "MAC")

    trocada = await cliente.patch(
        f"{BASE}/tipos-unidade/{tipo}",
        json={"area_tecnica_id": mental},
        headers=bearer(app, gestor),
    )
    inexistente = await cliente.patch(
        f"{BASE}/tipos-unidade/{tipo}", json={"area_tecnica_id": 32000}, headers=bearer(app, gestor)
    )

    assert trocada.status_code == 200
    assert trocada.json()["area_tecnica_id"] == mental
    assert inexistente.status_code == 422
    [evento] = await eventos(sessoes, "referencia.atualizada")
    assert evento["changes"] == [{"campo": "area_tecnica_id", "de": mac, "para": mental}]


async def test_patch_sem_mudanca_nao_audita(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """006/R7.2 (como 006/R3 e 011/R6.4): enviar os valores que o item já tem não é alterar."""
    gestor = await logado(sessoes, ("GESTOR_DADOS", GLOBAL))
    area = await id_pelo_codigo(sessoes, "area", "APS")

    resposta = await cliente.patch(
        f"{BASE}/areas-tecnicas/{area}",
        json={"codigo": "APS", "ativo": True},
        headers=bearer(app, gestor),
    )

    assert resposta.status_code == 200
    assert await eventos(sessoes, "referencia.atualizada") == []


@pytest.mark.parametrize(
    "corpo",
    [{"nome": None}, {"ativo": None}, {"codigo": ""}, {"outro": 1}],
    ids=["nome-nulo", "ativo-nulo", "codigo-vazio", "campo-a-mais"],
)
async def test_alteracao_com_campos_invalidos_responde_422(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes, corpo: dict[str, object]
) -> None:
    """006/R7.2: os campos não aceitam nulo nem vazio; campo desconhecido é recusado."""
    gestor = await logado(sessoes, ("GESTOR_DADOS", GLOBAL))
    area = await id_pelo_codigo(sessoes, "area", "APS")

    resposta = await cliente.patch(
        f"{BASE}/areas-tecnicas/{area}", json=corpo, headers=bearer(app, gestor)
    )

    assert resposta.status_code == 422


@pytest.mark.parametrize("tabela", TABELAS)
async def test_item_inexistente_responde_404(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes, tabela: str
) -> None:
    """006/R7.2."""
    gestor = await logado(sessoes, ("GESTOR_DADOS", GLOBAL))

    resposta = await cliente.patch(
        f"{BASE}/{tabela}/32000", json={"nome": "X"}, headers=bearer(app, gestor)
    )

    assert resposta.status_code == 404


# --- Permissão (R7.2) ---


@pytest.mark.parametrize(
    "papel",
    [
        "COORD_TECNICO",
        "TECNICO_DISTRITAL",
        "GESTOR_UNIDADE",
        "DIRETORIA",
        "AUDITOR",
        "ADMIN_TI",
    ],
)
async def test_so_o_gestor_de_dados_inclui_ou_altera(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes, papel: str
) -> None:
    """006/R7.2, 003/R4.6: os outros papéis, mesmo globais, recebem 403, auditado como
    `acesso.negado`; nada muda."""
    usuario = await logado(sessoes, (papel, GLOBAL))
    area = await id_pelo_codigo(sessoes, "area", "APS")

    inclusao = await cliente.post(
        f"{BASE}/areas-tecnicas",
        json={"codigo": "NOVA", "nome": "Nova"},
        headers=bearer(app, usuario),
    )
    alteracao = await cliente.patch(
        f"{BASE}/areas-tecnicas/{area}", json={"ativo": False}, headers=bearer(app, usuario)
    )

    assert inclusao.status_code == 403
    assert alteracao.status_code == 403
    negados = await eventos(sessoes, "acesso.negado")
    assert [n["metadata"]["permissao"] for n in negados] == ["regra_validacao:manage"] * 2
    assert await eventos(sessoes, "referencia.criada") == []
    assert await eventos(sessoes, "referencia.atualizada") == []
