"""Administração de atribuições de papel (003/T7).

Design da 003 § Rotas (`GET/POST/DELETE /api/v1/admin/atribuicoes`, `papel:assign`) e as notas
da 003/T3 em "Perguntas em aberto": o escopo exigido é o nível não global do papel, e papel só
com `G` exige escopo global.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
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
from tests.integration.acesso import GLOBAL, Sessoes, bearer, eventos, id_pelo_codigo, logado
from tests.integration.postgres import BancoDeTeste, motor
from tests.integration.registry import cadastro

ROTA = "/api/v1/admin/atribuicoes"


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


@pytest.fixture
async def admin(app: FastAPI, sessoes: Sessoes) -> dict[str, str]:
    """Cabeçalho de um Admin TI, o único papel com `papel:assign`."""
    return bearer(app, await logado(sessoes, ("ADMIN_TI", GLOBAL)))


async def _atribuicoes_de(sessoes: Sessoes, usuario: UUID) -> list[dict[str, Any]]:
    async with sessoes() as sessao:
        resultado = await sessao.execute(
            text(
                "SELECT ra.id, r.code AS papel, ra.scope_type, ra.scope_id, ra.origin,"
                " ra.granted_by, ra.valid_until"
                " FROM role_assignments ra JOIN roles r ON r.id = ra.role_id"
                " WHERE ra.user_id = :usuario ORDER BY r.code"
            ),
            {"usuario": usuario},
        )
        return [dict(linha) for linha in resultado.mappings()]


async def _versao(sessoes: Sessoes, usuario: UUID) -> int:
    async with sessoes() as sessao:
        versao = await sessao.scalar(
            text("SELECT authz_version FROM users WHERE id = :id"), {"id": usuario}
        )
    return int(versao)


async def inserir_unidade(sessoes: Sessoes) -> UUID:
    async with sessoes() as sessao, sessao.begin():
        conexao = await sessao.connection()
        return await cadastro.inserir_unidade(conexao, f"CAPS {uuid7().hex}")


def _corpo(usuario: UUID, papel: str, tipo: str, id_: str | None, **extra: Any) -> dict[str, Any]:
    return {
        "usuario_id": str(usuario),
        "papel": papel,
        "escopo": {"tipo": tipo, "id": id_},
        **extra,
    }


async def test_admin_atribui_gestor_de_unidade_no_escopo_da_unidade(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """003/R2.1 e R2.4: a atribuição vale, guarda quem concedeu e é auditada como
    `papel.atribuido`; o alvo ganha a permissão na próxima requisição (R4.5)."""
    admin = await logado(sessoes, ("ADMIN_TI", GLOBAL))
    alvo = await logado(sessoes)
    unidade = await inserir_unidade(sessoes)
    versao_antes = await _versao(sessoes, alvo.user_id)

    resposta = await cliente.post(
        ROTA,
        json=_corpo(alvo.user_id, "GESTOR_UNIDADE", "unidade", str(unidade)),
        headers=bearer(app, admin),
    )

    assert resposta.status_code == 201
    corpo = resposta.json()
    assert corpo["usuario_id"] == str(alvo.user_id)
    assert corpo["papel"] == "GESTOR_UNIDADE"
    assert corpo["escopo"] == {"tipo": "unidade", "id": str(unidade)}
    assert corpo["origem"] == "direta"
    assert corpo["concedida_por"] == str(admin.user_id)
    assert corpo["valido_ate"] is None
    assert resposta.headers["Location"] == f"{ROTA}/{corpo['id']}"

    [linha] = await _atribuicoes_de(sessoes, alvo.user_id)
    assert str(linha["id"]) == corpo["id"]
    assert (linha["scope_type"], linha["scope_id"], linha["origin"]) == (
        "unidade",
        str(unidade),
        "direct",
    )
    assert linha["granted_by"] == admin.user_id
    assert await _versao(sessoes, alvo.user_id) == versao_antes + 1

    [evento] = await eventos(sessoes, "papel.atribuido")
    assert evento["actor_user_id"] == admin.user_id
    assert evento["session_id"] == admin.id
    assert (evento["entity_type"], evento["entity_id"]) == ("atribuicao", corpo["id"])
    mudancas = {m["campo"]: m["para"] for m in evento["changes"]}
    assert mudancas == {
        "usuario_id": str(alvo.user_id),
        "papel": "GESTOR_UNIDADE",
        "escopo_tipo": "unidade",
        "escopo_id": str(unidade),
        "valido_ate": None,
    }

    perfil = await cliente.get("/api/v1/me", headers=bearer(app, alvo))
    assert perfil.json()["permissoes"]["unidade:update"] == [
        {"tipo": "unidade", "id": str(unidade)}
    ]


async def test_papel_de_distrito_e_de_area_aceitam_o_proprio_nivel(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes, admin: dict[str, str]
) -> None:
    """003/R2.1: `TECNICO_DISTRITAL` com distrito, `COORD_TECNICO` com área técnica e
    `DIRETORIA` (só `G`) com escopo global."""
    alvo = await logado(sessoes)
    ds3 = str(await id_pelo_codigo(sessoes, "distrito", "DS-III"))
    area = str(await id_pelo_codigo(sessoes, "area", "SAUDE_MENTAL"))

    for corpo in (
        _corpo(alvo.user_id, "TECNICO_DISTRITAL", "distrito", ds3),
        _corpo(alvo.user_id, "COORD_TECNICO", "area", area),
        _corpo(alvo.user_id, "DIRETORIA", "global", None),
    ):
        resposta = await cliente.post(ROTA, json=corpo, headers=admin)
        assert resposta.status_code == 201, resposta.text

    linhas = await _atribuicoes_de(sessoes, alvo.user_id)
    assert {(x["papel"], x["scope_type"], x["scope_id"]) for x in linhas} == {
        ("COORD_TECNICO", "area", area),
        ("DIRETORIA", "global", None),
        ("TECNICO_DISTRITAL", "distrito", ds3),
    }


@pytest.mark.parametrize(
    ("papel", "tipo"),
    [
        ("GESTOR_UNIDADE", "distrito"),
        ("GESTOR_UNIDADE", "global"),
        ("TECNICO_DISTRITAL", "global"),
        ("TECNICO_DISTRITAL", "area"),
        ("TECNICO_DISTRITAL", "unidade"),
        ("COORD_TECNICO", "distrito"),
        ("COORD_TECNICO", "global"),
        ("DIRETORIA", "distrito"),
        ("GESTOR_DADOS", "area"),
        ("ADMIN_TI", "unidade"),
        ("AUDITOR", "area"),
    ],
)
async def test_escopo_incompativel_com_o_papel_responde_422(
    app: FastAPI,
    cliente: httpx.AsyncClient,
    sessoes: Sessoes,
    admin: dict[str, str],
    papel: str,
    tipo: str,
) -> None:
    """003/R2.1 e R2.2: escopo maior que o do papel, menor, ou do outro eixo, é recusado; papel
    só com `G` exige escopo global (nota da 003/T3)."""
    alvo = await logado(sessoes)
    ids = {
        "global": None,
        "area": str(await id_pelo_codigo(sessoes, "area", "SAUDE_MENTAL")),
        "distrito": str(await id_pelo_codigo(sessoes, "distrito", "DS-III")),
        "unidade": str(await inserir_unidade(sessoes)),
    }

    resposta = await cliente.post(
        ROTA, json=_corpo(alvo.user_id, papel, tipo, ids[tipo]), headers=admin
    )

    assert resposta.status_code == 422
    assert [e["campo"] for e in resposta.json()["errors"]] == ["escopo.tipo"]
    assert await _atribuicoes_de(sessoes, alvo.user_id) == []


@pytest.mark.parametrize(
    ("papel", "tipo", "id_"),
    [
        ("GESTOR_UNIDADE", "unidade", "0190f3c0-0000-7000-8000-000000000000"),
        ("GESTOR_UNIDADE", "unidade", "não-é-uuid"),
        ("TECNICO_DISTRITAL", "distrito", "32000"),
        ("TECNICO_DISTRITAL", "distrito", "99999999999"),
        ("TECNICO_DISTRITAL", "distrito", "DS-III"),
        ("COORD_TECNICO", "area", "32000"),
        ("COORD_TECNICO", "area", None),
        ("DIRETORIA", "global", "1"),
    ],
)
async def test_escopo_inexistente_responde_422(
    cliente: httpx.AsyncClient,
    sessoes: Sessoes,
    admin: dict[str, str],
    papel: str,
    tipo: str,
    id_: str | None,
) -> None:
    """003/R2.2: escopo que não existe (ou id fora do formato do nível) é recusado."""
    alvo = await logado(sessoes)

    resposta = await cliente.post(ROTA, json=_corpo(alvo.user_id, papel, tipo, id_), headers=admin)

    assert resposta.status_code == 422
    assert [e["campo"] for e in resposta.json()["errors"]] == ["escopo.id"]
    assert await _atribuicoes_de(sessoes, alvo.user_id) == []


async def test_papel_ou_usuario_inexistente_responde_422(
    cliente: httpx.AsyncClient, sessoes: Sessoes, admin: dict[str, str]
) -> None:
    """003/R2.1: só se atribui papel do catálogo a usuário que existe."""
    alvo = await logado(sessoes)

    sem_papel = await cliente.post(
        ROTA, json=_corpo(alvo.user_id, "SUPER_USUARIO", "global", None), headers=admin
    )
    sem_usuario = await cliente.post(
        ROTA, json=_corpo(uuid7(), "DIRETORIA", "global", None), headers=admin
    )

    assert sem_papel.status_code == 422
    assert [e["campo"] for e in sem_papel.json()["errors"]] == ["papel"]
    assert sem_usuario.status_code == 422
    assert [e["campo"] for e in sem_usuario.json()["errors"]] == ["usuario_id"]


async def test_atribuicao_com_expiracao_vale_ate_a_data(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes, admin: dict[str, str]
) -> None:
    """003/R2.3: a expiração é opcional e fica gravada; data no passado é recusada."""
    alvo = await logado(sessoes)
    amanha = datetime.now(UTC) + timedelta(days=1)
    ontem = datetime.now(UTC) - timedelta(days=1)

    vencida = await cliente.post(
        ROTA,
        json=_corpo(alvo.user_id, "DIRETORIA", "global", None, valido_ate=ontem.isoformat()),
        headers=admin,
    )
    resposta = await cliente.post(
        ROTA,
        json=_corpo(alvo.user_id, "DIRETORIA", "global", None, valido_ate=amanha.isoformat()),
        headers=admin,
    )

    assert vencida.status_code == 422
    assert [e["campo"] for e in vencida.json()["errors"]] == ["valido_ate"]
    assert resposta.status_code == 201
    assert datetime.fromisoformat(resposta.json()["valido_ate"]) == amanha
    [linha] = await _atribuicoes_de(sessoes, alvo.user_id)
    assert linha["valid_until"] == amanha


async def test_listagem_ignora_atribuicao_expirada(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes, admin: dict[str, str]
) -> None:
    """003/R2.3: a atribuição expirada fica de fora da listagem, filtrada pelo usuário."""
    alvo = await logado(sessoes, ("DIRETORIA", GLOBAL))
    outro = await logado(sessoes, ("AUDITOR", GLOBAL))
    async with sessoes() as sessao, sessao.begin():
        await sessao.execute(
            text(
                "INSERT INTO role_assignments"
                " (id, user_id, role_id, scope_type, scope_id, origin, valid_until)"
                " SELECT :id, :usuario, id, 'global', NULL, 'direct', :ate"
                " FROM roles WHERE code = 'GESTOR_DADOS'"
            ),
            {"id": uuid7(), "usuario": alvo.user_id, "ate": datetime.now(UTC) - timedelta(days=1)},
        )

    resposta = await cliente.get(ROTA, params={"usuario_id": str(alvo.user_id)}, headers=admin)

    assert resposta.status_code == 200
    pagina = resposta.json()
    assert pagina["total"] == 1
    [item] = pagina["itens"]
    assert (item["usuario_id"], item["papel"], item["escopo"]) == (
        str(alvo.user_id),
        "DIRETORIA",
        {"tipo": "global", "id": None},
    )
    todas = await cliente.get(ROTA, headers=admin)
    assert {i["usuario_id"] for i in todas.json()["itens"]} >= {
        str(alvo.user_id),
        str(outro.user_id),
    }


async def test_atribuicao_repetida_responde_409(
    cliente: httpx.AsyncClient, sessoes: Sessoes, admin: dict[str, str]
) -> None:
    """003/R2.1: o mesmo papel no mesmo escopo, já vigente, não é atribuído de novo."""
    alvo = await logado(sessoes, ("DIRETORIA", GLOBAL))

    resposta = await cliente.post(
        ROTA, json=_corpo(alvo.user_id, "DIRETORIA", "global", None), headers=admin
    )

    assert resposta.status_code == 409
    assert len(await _atribuicoes_de(sessoes, alvo.user_id)) == 1


async def test_ninguem_atribui_papel_a_si_mesmo(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """003/R2.5: segregação de funções; o 403 é auditado como `acesso.negado` (R4.6)."""
    admin = await logado(sessoes, ("ADMIN_TI", GLOBAL))

    resposta = await cliente.post(
        ROTA, json=_corpo(admin.user_id, "GESTOR_DADOS", "global", None), headers=bearer(app, admin)
    )

    assert resposta.status_code == 403
    assert [x["papel"] for x in await _atribuicoes_de(sessoes, admin.user_id)] == ["ADMIN_TI"]
    assert await eventos(sessoes, "papel.atribuido") == []
    [negado] = await eventos(sessoes, "acesso.negado")
    assert negado["actor_user_id"] == admin.user_id
    assert negado["metadata"]["permissao"] == "papel:assign"
    assert (negado["entity_type"], negado["entity_id"]) == ("usuario", str(admin.user_id))


async def test_admin_remove_atribuicao_e_o_alvo_perde_a_permissao(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """003/R2.4 e R4.5: `papel.removido` com quem removeu, e a permissão some na próxima
    requisição do alvo."""
    admin = await logado(sessoes, ("ADMIN_TI", GLOBAL))
    alvo = await logado(sessoes, ("GESTOR_DADOS", GLOBAL))
    [atribuicao] = await _atribuicoes_de(sessoes, alvo.user_id)
    antes = await cliente.get("/api/v1/me", headers=bearer(app, alvo))
    assert "unidade:create" in antes.json()["permissoes"]

    resposta = await cliente.delete(f"{ROTA}/{atribuicao['id']}", headers=bearer(app, admin))

    assert resposta.status_code == 204
    assert await _atribuicoes_de(sessoes, alvo.user_id) == []
    [evento] = await eventos(sessoes, "papel.removido")
    assert evento["actor_user_id"] == admin.user_id
    assert (evento["entity_type"], evento["entity_id"]) == ("atribuicao", str(atribuicao["id"]))
    mudancas = {m["campo"]: (m["de"], m["para"]) for m in evento["changes"]}
    assert mudancas["papel"] == ("GESTOR_DADOS", None)
    assert mudancas["usuario_id"] == (str(alvo.user_id), None)
    depois = await cliente.get("/api/v1/me", headers=bearer(app, alvo))
    assert depois.json()["permissoes"] == {}


async def test_remover_atribuicao_inexistente_responde_404(
    cliente: httpx.AsyncClient, admin: dict[str, str]
) -> None:
    """003/R2: a atribuição pedida não existe."""
    resposta = await cliente.delete(f"{ROTA}/{uuid7()}", headers=admin)

    assert resposta.status_code == 404


async def test_atribuicao_de_grupo_nao_e_removida_pela_rota(
    cliente: httpx.AsyncClient, sessoes: Sessoes, admin: dict[str, str]
) -> None:
    """003/R3.3: a atribuição derivada de grupo só sai pelo mapeamento (409)."""
    alvo = await logado(sessoes)
    atribuicao, mapeamento = uuid7(), uuid7()
    async with sessoes() as sessao, sessao.begin():
        await sessao.execute(
            text(
                "INSERT INTO group_role_mappings (id, group_id, role_id, scope_type, created_by)"
                " SELECT :id, :grupo, id, 'global', :usuario FROM roles WHERE code = 'DIRETORIA'"
            ),
            {"id": mapeamento, "grupo": uuid7(), "usuario": alvo.user_id},
        )
        await sessao.execute(
            text(
                "INSERT INTO role_assignments"
                " (id, user_id, role_id, scope_type, origin, group_mapping_id)"
                " SELECT :id, :usuario, id, 'global', 'group', :mapeamento"
                " FROM roles WHERE code = 'DIRETORIA'"
            ),
            {"id": atribuicao, "usuario": alvo.user_id, "mapeamento": mapeamento},
        )

    resposta = await cliente.delete(f"{ROTA}/{atribuicao}", headers=admin)

    assert resposta.status_code == 409
    assert len(await _atribuicoes_de(sessoes, alvo.user_id)) == 1
    assert await eventos(sessoes, "papel.removido") == []


async def test_sem_token_responde_401(cliente: httpx.AsyncClient) -> None:
    """Design da 003 § Rotas: as rotas de administração exigem autenticação."""
    assert (await cliente.get(ROTA)).status_code == 401
    assert (await cliente.post(ROTA, json={})).status_code == 401
    assert (await cliente.delete(f"{ROTA}/{uuid7()}")).status_code == 401


async def test_sem_papel_assign_responde_403(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """003/R4.2 e design § Rotas: o Gestor de Dados não atribui papel (só o Admin TI)."""
    gestor = bearer(app, await logado(sessoes, ("GESTOR_DADOS", GLOBAL)))
    alvo = await logado(sessoes, ("DIRETORIA", GLOBAL))
    [atribuicao] = await _atribuicoes_de(sessoes, alvo.user_id)

    listar = await cliente.get(ROTA, headers=gestor)
    criar = await cliente.post(
        ROTA, json=_corpo(alvo.user_id, "AUDITOR", "global", None), headers=gestor
    )
    remover = await cliente.delete(f"{ROTA}/{atribuicao['id']}", headers=gestor)

    assert (listar.status_code, criar.status_code, remover.status_code) == (403, 403, 403)
    assert len(await _atribuicoes_de(sessoes, alvo.user_id)) == 1


async def test_corpo_invalido_responde_422(
    cliente: httpx.AsyncClient, sessoes: Sessoes, admin: dict[str, str]
) -> None:
    """Entrada validada pelo schema: campo a mais, nível desconhecido ou id longo demais."""
    alvo = await logado(sessoes)

    for corpo in (
        _corpo(alvo.user_id, "DIRETORIA", "global", None, extra=1),
        _corpo(alvo.user_id, "DIRETORIA", "planeta", None),
        _corpo(alvo.user_id, "GESTOR_UNIDADE", "unidade", "x" * 37),
        {"papel": "DIRETORIA", "escopo": {"tipo": "global", "id": None}},
    ):
        resposta = await cliente.post(ROTA, json=corpo, headers=admin)
        assert resposta.status_code == 422, corpo
