"""`PATCH /api/v1/unidades/{id}`: atualizar unidade com `If-Match` (006/T5).

Design da 006 § Rotas, § Campos estruturais e § Diff e auditoria. A versão sobe pelo trigger da
011 (R8), nunca pela aplicação; o `ETag` da resposta é a versão lida de volta do banco. A versão
invalidada por alteração fora da API está em `test_versao_fora_da_api.py` (011/T17).
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

from src.core.ids import uuid7
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
from tests.integration.registry.cadastro import inserir_unidade

ROTA = "/api/v1/unidades/{id}"


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


async def _unidade(
    sessoes: Sessoes, nome: str = "CAPS Galdino Loreto", *, cnes: str | None = "2345678"
) -> UUID:
    """CAPS II (Saúde Mental) no DS I, ativa, versão 1."""
    async with sessoes() as sessao, sessao.begin():
        return await inserir_unidade(await sessao.connection(), nome, cnes=cnes)


async def _gravada(sessoes: Sessoes, unidade: UUID) -> dict[str, Any]:
    """Os campos que os testes mexem, como estão no banco."""
    async with sessoes() as sessao:
        resultado = await sessao.execute(
            text(
                "SELECT name, cnes, phone, district_id, unit_type_id, version"
                " FROM health_units WHERE id = :id"
            ),
            {"id": unidade},
        )
        return dict(resultado.mappings().one())


async def _atribuicao(sessoes: Sessoes, papel: str, unidade: UUID) -> Atribuicao:
    """O papel com o escopo mais próximo da unidade (CAPS II é Saúde Mental, no DS I)."""
    escopos = {
        "COORD_TECNICO": ("area", str(await id_pelo_codigo(sessoes, "area", "SAUDE_MENTAL"))),
        "TECNICO_DISTRITAL": ("distrito", str(await id_pelo_codigo(sessoes, "distrito", "DS-I"))),
        "GESTOR_UNIDADE": ("unidade", str(unidade)),
    }
    return papel, escopos.get(papel, GLOBAL)


def _cabecalhos(app: FastAPI, usuario: Any, versao: str | None = '"1"') -> dict[str, str]:
    cabecalhos = bearer(app, usuario)
    if versao is not None:
        cabecalhos["If-Match"] = versao
    return cabecalhos


async def test_gestor_da_unidade_aplica_so_os_campos_enviados_e_audita_cada_campo(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """006/R3.1, R3.5: aplica só o que veio, responde 200 com a versão nova no `ETag` (lida do
    banco, que a incrementou) e registra `unidade.atualizada` com `{campo, de, para}`."""
    unidade = await _unidade(sessoes)
    gestor = await logado(sessoes, await _atribuicao(sessoes, "GESTOR_UNIDADE", unidade))

    resposta = await cliente.patch(
        _rota(unidade),
        json={"telefone": "(81) 3355-1234", "nome": "CAPS Galdino Loreto II"},
        headers=_cabecalhos(app, gestor),
    )

    assert resposta.status_code == 200
    assert resposta.headers["etag"] == '"2"'
    corpo = resposta.json()
    assert (corpo["nome"], corpo["telefone"], corpo["cnes"], corpo["versao"]) == (
        "CAPS Galdino Loreto II",
        "(81) 3355-1234",
        "2345678",
        2,
    )
    gravada = await _gravada(sessoes, unidade)
    assert (gravada["name"], gravada["phone"], gravada["version"]) == (
        "CAPS Galdino Loreto II",
        "(81) 3355-1234",
        2,
    )
    [evento] = await eventos(sessoes, "unidade.atualizada")
    assert evento["entity_type"] == "unidade"
    assert evento["entity_id"] == str(unidade)
    assert evento["actor_user_id"] == gestor.user_id
    # Na ordem das colunas, seja qual for a do corpo.
    assert evento["changes"] == [
        {"campo": "name", "de": "CAPS Galdino Loreto", "para": "CAPS Galdino Loreto II"},
        {"campo": "phone", "de": None, "para": "(81) 3355-1234"},
    ]


@pytest.mark.parametrize("versao", ['"2"', '"0"', "*", "1", 'W/"1"', '"1", "2"'])
async def test_if_match_que_nao_e_a_versao_atual_responde_412_e_nada_muda(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes, versao: str
) -> None:
    """006/R3.2: só a versão atual, como veio no `ETag`, deixa alterar."""
    unidade = await _unidade(sessoes)
    gestor = await logado(sessoes, ("GESTOR_DADOS", GLOBAL))

    resposta = await cliente.patch(
        _rota(unidade), json={"telefone": "8133551234"}, headers=_cabecalhos(app, gestor, versao)
    )

    assert resposta.status_code == 412
    assert resposta.json()["title"] == "Versão desatualizada"
    assert (await _gravada(sessoes, unidade))["phone"] is None
    assert await eventos(sessoes, "unidade.atualizada") == []


async def test_versao_lida_antes_de_outra_alteracao_pela_api_responde_412(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """006/R3.2: quem leu a versão 1 não sobrescreve a alteração que outra pessoa já fez."""
    unidade = await _unidade(sessoes)
    gestor = await logado(sessoes, ("GESTOR_DADOS", GLOBAL))
    primeira = await cliente.patch(
        _rota(unidade), json={"telefone": "8133551234"}, headers=_cabecalhos(app, gestor)
    )

    segunda = await cliente.patch(
        _rota(unidade), json={"telefone": "8133559999"}, headers=_cabecalhos(app, gestor)
    )

    assert (primeira.status_code, segunda.status_code) == (200, 412)
    gravada = await _gravada(sessoes, unidade)
    assert (gravada["phone"], gravada["version"]) == ("8133551234", 2)


async def test_sem_if_match_responde_428_e_nada_muda(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """006/R3.2: a alteração exige `If-Match`."""
    unidade = await _unidade(sessoes)
    gestor = await logado(sessoes, ("GESTOR_DADOS", GLOBAL))

    resposta = await cliente.patch(
        _rota(unidade), json={"telefone": "8133551234"}, headers=_cabecalhos(app, gestor, None)
    )

    assert resposta.status_code == 428
    assert (await _gravada(sessoes, unidade))["phone"] is None


@pytest.mark.parametrize(
    "corpo",
    [{}, {"nome": "CAPS Galdino Loreto", "cnes": "2345678"}, {"nome": " CAPS Galdino Loreto "}],
    ids=["vazio", "mesmos-valores", "nome-com-espacos"],
)
async def test_patch_sem_mudanca_responde_200_sem_auditar_nem_mudar_a_versao(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes, corpo: dict[str, Any]
) -> None:
    """006/R3.6: nada mudou, nada é gravado nem auditado; o `ETag` continua o mesmo. Enviar um
    campo estrutural com o valor que ele já tem não é alterá-lo (R3.4), nem para o gestor."""
    unidade = await _unidade(sessoes)
    gestor = await logado(sessoes, await _atribuicao(sessoes, "GESTOR_UNIDADE", unidade))

    resposta = await cliente.patch(_rota(unidade), json=corpo, headers=_cabecalhos(app, gestor))

    assert resposta.status_code == 200
    assert resposta.headers["etag"] == '"1"'
    assert resposta.json()["versao"] == 1
    assert (await _gravada(sessoes, unidade))["version"] == 1
    assert await eventos(sessoes, "unidade.atualizada") == []


async def test_gestor_de_outra_unidade_responde_403_e_nada_muda(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """006/R3.3: gestor da unidade A não altera a B; o 403 é auditado com a unidade."""
    unidade_a = await _unidade(sessoes, "CAPS José Lucena", cnes=None)
    unidade_b = await _unidade(sessoes)
    gestor_a = await logado(sessoes, await _atribuicao(sessoes, "GESTOR_UNIDADE", unidade_a))

    resposta = await cliente.patch(
        _rota(unidade_b), json={"telefone": "8133551234"}, headers=_cabecalhos(app, gestor_a)
    )

    assert resposta.status_code == 403
    [negacao] = await eventos(sessoes, "acesso.negado")
    assert (negacao["entity_type"], negacao["entity_id"]) == ("unidade", str(unidade_b))
    assert negacao["metadata"] == {"permissao": "unidade:update", "rota": f"PATCH {ROTA}"}
    assert (await _gravada(sessoes, unidade_b))["phone"] is None
    assert await eventos(sessoes, "unidade.atualizada") == []


@pytest.mark.parametrize("papel", ["DIRETORIA", "AUDITOR", "ADMIN_TI"])
async def test_papel_sem_unidade_update_responde_403(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes, papel: str
) -> None:
    """006/R3.1, 003/R4.2: sem `unidade:update`, nada muda."""
    unidade = await _unidade(sessoes)
    usuario = await logado(sessoes, (papel, GLOBAL))

    resposta = await cliente.patch(
        _rota(unidade), json={"telefone": "8133551234"}, headers=_cabecalhos(app, usuario)
    )

    assert resposta.status_code == 403
    assert (await _gravada(sessoes, unidade))["phone"] is None


async def test_unidade_inexistente_responde_404(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """003/R4.3: com a permissão, a unidade que não existe dá 404."""
    gestor = await logado(sessoes, ("GESTOR_DADOS", GLOBAL))

    resposta = await cliente.patch(
        _rota(uuid7()), json={"telefone": "8133551234"}, headers=_cabecalhos(app, gestor)
    )

    assert resposta.status_code == 404


async def _com_ids(sessoes: Sessoes, corpo: dict[str, Any]) -> dict[str, Any]:
    """Troca o código do distrito e do tipo de unidade no corpo pelo id semeado."""
    referencias = {"distrito_id": "distrito", "tipo_unidade_id": "tipo_unidade"}
    return {
        campo: (
            await id_pelo_codigo(sessoes, referencias[campo], valor)
            if campo in referencias
            else valor
        )
        for campo, valor in corpo.items()
    }


@pytest.mark.parametrize(
    ("papel", "corpo", "campos"),
    [
        ("GESTOR_UNIDADE", {"cnes": "7654321"}, ["cnes"]),
        ("GESTOR_UNIDADE", {"distrito_id": "DS-II"}, ["distrito_id"]),
        ("TECNICO_DISTRITAL", {"tipo_unidade_id": "CAPS_AD"}, ["tipo_unidade_id"]),
        (
            "TECNICO_DISTRITAL",
            {"telefone": "8133551234", "cnes": None, "distrito_id": "DS-II"},
            ["distrito_id", "cnes"],
        ),
    ],
    ids=["gestor-cnes", "gestor-distrito", "tecnico-tipo", "tecnico-dois-campos"],
)
async def test_gestor_e_tecnico_distrital_nao_alteram_campo_estrutural(
    app: FastAPI,
    cliente: httpx.AsyncClient,
    sessoes: Sessoes,
    papel: str,
    corpo: dict[str, Any],
    campos: list[str],
) -> None:
    """006/R3.4: distrito, tipo e CNES só com escopo global ou de área; o 403 aponta os campos,
    é auditado com a unidade, e nem os outros campos enviados mudam."""
    unidade = await _unidade(sessoes)
    usuario = await logado(sessoes, await _atribuicao(sessoes, papel, unidade))
    corpo = await _com_ids(sessoes, corpo)

    resposta = await cliente.patch(_rota(unidade), json=corpo, headers=_cabecalhos(app, usuario))

    assert resposta.status_code == 403
    assert resposta.json()["campos"] == campos
    [negacao] = await eventos(sessoes, "acesso.negado")
    assert (negacao["entity_type"], negacao["entity_id"]) == ("unidade", str(unidade))
    assert await _gravada(sessoes, unidade) == {
        "name": "CAPS Galdino Loreto",
        "cnes": "2345678",
        "phone": None,
        "district_id": await id_pelo_codigo(sessoes, "distrito", "DS-I"),
        "unit_type_id": await id_pelo_codigo(sessoes, "tipo_unidade", "CAPS_II"),
        "version": 1,
    }
    assert await eventos(sessoes, "unidade.atualizada") == []


@pytest.mark.parametrize("papel", ["GESTOR_DADOS", "COORD_TECNICO"])
async def test_gestor_de_dados_e_coordenador_da_area_alteram_campo_estrutural(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes, papel: str
) -> None:
    """006/R3.4, R3.5: com escopo global ou na área técnica da unidade, distrito, tipo e CNES
    mudam, e cada um entra na auditoria."""
    unidade = await _unidade(sessoes)
    usuario = await logado(sessoes, await _atribuicao(sessoes, papel, unidade))
    ds_i = await id_pelo_codigo(sessoes, "distrito", "DS-I")
    caps_ii = await id_pelo_codigo(sessoes, "tipo_unidade", "CAPS_II")
    corpo = await _com_ids(
        sessoes, {"cnes": "7654321", "distrito_id": "DS-II", "tipo_unidade_id": "CAPS_AD"}
    )

    resposta = await cliente.patch(_rota(unidade), json=corpo, headers=_cabecalhos(app, usuario))

    assert resposta.status_code == 200
    gravada = await _gravada(sessoes, unidade)
    assert (gravada["cnes"], gravada["district_id"], gravada["unit_type_id"]) == (
        "7654321",
        corpo["distrito_id"],
        corpo["tipo_unidade_id"],
    )
    [evento] = await eventos(sessoes, "unidade.atualizada")
    assert evento["changes"] == [
        {"campo": "unit_type_id", "de": caps_ii, "para": corpo["tipo_unidade_id"]},
        {"campo": "district_id", "de": ds_i, "para": corpo["distrito_id"]},
        {"campo": "cnes", "de": "2345678", "para": "7654321"},
    ]


async def test_coordenador_de_outra_area_nao_altera_a_unidade(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """006/R3.3: escopo de área cobre só as unidades dos tipos da área (CAPS II é Saúde Mental)."""
    unidade = await _unidade(sessoes)
    aps = await id_pelo_codigo(sessoes, "area", "APS")
    coordenador = await logado(sessoes, ("COORD_TECNICO", ("area", str(aps))))

    resposta = await cliente.patch(
        _rota(unidade), json={"cnes": "7654321"}, headers=_cabecalhos(app, coordenador)
    )

    assert resposta.status_code == 403
    assert (await _gravada(sessoes, unidade))["cnes"] == "2345678"


async def test_coordenador_nao_troca_o_tipo_para_um_de_area_fora_do_seu_escopo(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """006/R1.1, R3.4: o Coordenador Técnico de Saúde Mental não muda o CAPS II para USF (APS):
    a área do tipo novo também tem de estar no escopo, como no cadastro. O 403 aponta o campo, é
    auditado com a unidade e nada muda (006/T5, resolvido na revisão)."""
    unidade = await _unidade(sessoes)
    coordenador = await logado(sessoes, await _atribuicao(sessoes, "COORD_TECNICO", unidade))
    corpo = await _com_ids(sessoes, {"tipo_unidade_id": "USF"})

    resposta = await cliente.patch(
        _rota(unidade), json=corpo, headers=_cabecalhos(app, coordenador)
    )

    assert resposta.status_code == 403
    assert resposta.json()["campos"] == ["tipo_unidade_id"]
    [negacao] = await eventos(sessoes, "acesso.negado")
    assert (negacao["entity_type"], negacao["entity_id"]) == ("unidade", str(unidade))
    gravada = await _gravada(sessoes, unidade)
    assert gravada["unit_type_id"] == await id_pelo_codigo(sessoes, "tipo_unidade", "CAPS_II")
    assert gravada["version"] == 1
    assert await eventos(sessoes, "unidade.atualizada") == []


async def test_apagar_o_cnes_deixa_a_unidade_pendente(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """006/R3.1, R1.5: campo opcional enviado nulo é apagado."""
    unidade = await _unidade(sessoes)
    gestor = await logado(sessoes, ("GESTOR_DADOS", GLOBAL))

    resposta = await cliente.patch(
        _rota(unidade), json={"cnes": None}, headers=_cabecalhos(app, gestor)
    )

    assert resposta.status_code == 200
    assert (resposta.json()["cnes"], resposta.json()["cnes_pendente"]) == (None, True)
    [evento] = await eventos(sessoes, "unidade.atualizada")
    assert evento["changes"] == [{"campo": "cnes", "de": "2345678", "para": None}]


@pytest.mark.parametrize(
    ("corpo", "campo"),
    [
        ({"nome": None}, "nome"),
        ({"status": None}, "status"),
        ({"cnes": "123"}, "cnes"),
        ({"status": "fechada"}, "status"),
        ({"versao": 5}, "versao"),
        ({"distrito_id": 32000}, "distrito_id"),
        ({"tipo_unidade_id": 32000}, "tipo_unidade_id"),
    ],
    ids=[
        "nome-nulo",
        "status-nulo",
        "cnes-curto",
        "status-invalido",
        "extra",
        "distrito-inexistente",
        "tipo-inexistente",
    ],
)
async def test_campo_invalido_responde_422_e_nada_muda(
    app: FastAPI,
    cliente: httpx.AsyncClient,
    sessoes: Sessoes,
    corpo: dict[str, Any],
    campo: str,
) -> None:
    """006/R3.1, R1.2: só PATCH válido é aplicado; referência inexistente aponta o campo."""
    unidade = await _unidade(sessoes)
    gestor = await logado(sessoes, ("GESTOR_DADOS", GLOBAL))

    resposta = await cliente.patch(_rota(unidade), json=corpo, headers=_cabecalhos(app, gestor))

    assert resposta.status_code == 422
    assert [erro["campo"] for erro in resposta.json()["errors"]] == [campo]
    assert (await _gravada(sessoes, unidade))["version"] == 1
    assert await eventos(sessoes, "unidade.atualizada") == []


@pytest.mark.parametrize(
    "corpo", [{"cnes": "1111111"}, {"nome": "caps josé  lucena"}], ids=["cnes", "nome"]
)
async def test_cnes_ou_nome_de_outra_unidade_responde_409_apontando_a_existente(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes, corpo: dict[str, Any]
) -> None:
    """006/R1.3, R1.4 na atualização: o 409 indica a outra unidade, e nada muda."""
    outra = await _unidade(sessoes, "CAPS José Lucena", cnes="1111111")
    unidade = await _unidade(sessoes)
    gestor = await logado(sessoes, ("GESTOR_DADOS", GLOBAL))

    resposta = await cliente.patch(_rota(unidade), json=corpo, headers=_cabecalhos(app, gestor))

    assert resposta.status_code == 409
    assert resposta.json()["unidade_existente_id"] == str(outra)
    gravada = await _gravada(sessoes, unidade)
    assert (gravada["name"], gravada["cnes"], gravada["version"]) == (
        "CAPS Galdino Loreto",
        "2345678",
        1,
    )
    assert await eventos(sessoes, "unidade.atualizada") == []
