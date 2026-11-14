"""Mapeamentos grupo→papel e recálculo das atribuições derivadas (003/T8).

Design da 003 § Rotas (`GET/POST/DELETE /api/v1/admin/mapeamentos-grupo`, `papel:assign`). Os
grupos e os membros vêm do diretório (spec 004, ainda sem `groups` e `user_groups`): o teste
troca a porta `MembrosDeGrupo` por um diretório em memória, e a entrada e a saída de um grupo
(R3.2) chamam o recálculo como a sincronização da 004 fará.
"""

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.core.ids import uuid7
from src.main import create_app
from src.modules.access.application.mapeamentos import recalcular_derivadas_do_usuario
from src.modules.access.infrastructure.repository import (
    SqlRepositorioDeAtribuicoes,
    SqlRepositorioDeMapeamentos,
    SqlRepositorioDePermissoes,
)
from src.modules.audit.application.registrar import Ator
from src.modules.audit.infrastructure.repository import SqlAuditStore
from tests.factories import make_settings
from tests.integration.acesso import GLOBAL, Sessoes, bearer, eventos, logado
from tests.integration.postgres import BancoDeTeste, motor
from tests.integration.registry import cadastro

ROTA = "/api/v1/admin/mapeamentos-grupo"


class DiretorioEmMemoria:
    """`MembrosDeGrupo` de teste: grupo → membros ativos."""

    def __init__(self) -> None:
        self.grupos: dict[UUID, frozenset[UUID]] = {}

    def __call__(self, _sessao: AsyncSession) -> "DiretorioEmMemoria":
        return self

    async def membros_ativos(self, grupo_id: UUID) -> frozenset[UUID]:
        return self.grupos.get(grupo_id, frozenset())


@pytest.fixture
def diretorio() -> DiretorioEmMemoria:
    return DiretorioEmMemoria()


@pytest.fixture
async def app(banco: BancoDeTeste, diretorio: DiretorioEmMemoria) -> AsyncIterator[FastAPI]:
    app = create_app(make_settings(database_url=SecretStr(banco.url_api)))
    app.state.membros_de_grupo = diretorio
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


async def _atribuicoes_de(sessoes: Sessoes, usuario: UUID) -> list[dict[str, Any]]:
    async with sessoes() as sessao:
        resultado = await sessao.execute(
            text(
                "SELECT ra.id, r.code AS papel, ra.scope_type, ra.scope_id, ra.origin,"
                " ra.group_mapping_id, ra.granted_by"
                " FROM role_assignments ra JOIN roles r ON r.id = ra.role_id"
                " WHERE ra.user_id = :usuario ORDER BY ra.origin, r.code"
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


async def _inserir_unidade(sessoes: Sessoes) -> UUID:
    async with sessoes() as sessao, sessao.begin():
        conexao = await sessao.connection()
        return await cadastro.inserir_unidade(conexao, f"USF {uuid7().hex}")


def _corpo(grupo: UUID, papel: str, tipo: str, id_: str | None) -> dict[str, Any]:
    return {"grupo_id": str(grupo), "papel": papel, "escopo": {"tipo": tipo, "id": id_}}


async def _recalcular(sessoes: Sessoes, usuario: UUID, grupos: set[UUID]) -> None:
    """O que a sincronização da 004 fará quando o usuário entrar ou sair de grupos."""
    async with sessoes() as sessao, sessao.begin():
        await recalcular_derivadas_do_usuario(
            usuario,
            frozenset(grupos),
            ator=Ator(),
            mapeamentos=SqlRepositorioDeMapeamentos(sessao),
            atribuicoes=SqlRepositorioDeAtribuicoes(sessao),
            permissoes=SqlRepositorioDePermissoes(sessao),
            auditoria=SqlAuditStore(sessao),
            gerar_id=uuid7,
        )


async def test_criar_mapeamento_atribui_o_papel_aos_membros_ativos_do_grupo(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes, diretorio: DiretorioEmMemoria
) -> None:
    """003/R3.1: cada membro ativo ganha a atribuição de origem `group`, ligada ao mapeamento,
    na mesma transação do mapeamento e da auditoria; quem não é membro não ganha nada."""
    admin = await logado(sessoes, ("ADMIN_TI", GLOBAL))
    membro_a = await logado(sessoes)
    membro_b = await logado(sessoes)
    de_fora = await logado(sessoes)
    unidade = await _inserir_unidade(sessoes)
    grupo = uuid7()
    diretorio.grupos[grupo] = frozenset({membro_a.user_id, membro_b.user_id})
    versao_antes = await _versao(sessoes, membro_a.user_id)

    resposta = await cliente.post(
        ROTA,
        json=_corpo(grupo, "GESTOR_UNIDADE", "unidade", str(unidade)),
        headers=bearer(app, admin),
    )

    assert resposta.status_code == 201
    corpo = resposta.json()
    assert corpo["grupo_id"] == str(grupo)
    assert corpo["papel"] == "GESTOR_UNIDADE"
    assert corpo["escopo"] == {"tipo": "unidade", "id": str(unidade)}
    assert corpo["criado_por"] == str(admin.user_id)
    assert resposta.headers["Location"] == f"{ROTA}/{corpo['id']}"
    for membro in (membro_a, membro_b):
        [linha] = await _atribuicoes_de(sessoes, membro.user_id)
        assert (linha["papel"], linha["scope_type"], linha["scope_id"]) == (
            "GESTOR_UNIDADE",
            "unidade",
            str(unidade),
        )
        assert linha["origin"] == "group"
        assert str(linha["group_mapping_id"]) == corpo["id"]
        assert linha["granted_by"] is None
    assert await _atribuicoes_de(sessoes, de_fora.user_id) == []
    assert await _versao(sessoes, membro_a.user_id) == versao_antes + 1

    [criado] = await eventos(sessoes, "mapeamento.criado")
    assert criado["actor_user_id"] == admin.user_id
    assert (criado["entity_type"], criado["entity_id"]) == ("mapeamento_grupo", corpo["id"])
    assert {m["campo"]: m["para"] for m in criado["changes"]} == {
        "grupo_id": str(grupo),
        "papel": "GESTOR_UNIDADE",
        "escopo_tipo": "unidade",
        "escopo_id": str(unidade),
    }
    atribuidos = await eventos(sessoes, "papel.atribuido")
    assert len(atribuidos) == 2
    usuarios = set()
    for evento in atribuidos:
        mudancas = {m["campo"]: m["para"] for m in evento["changes"]}
        assert mudancas["mapeamento_id"] == corpo["id"]
        usuarios.add(mudancas["usuario_id"])
    assert usuarios == {str(membro_a.user_id), str(membro_b.user_id)}


async def test_membro_do_grupo_mapeado_ve_o_papel_no_me_na_proxima_requisicao(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes, diretorio: DiretorioEmMemoria
) -> None:
    """003/R3.1 e R4.5: a atribuição derivada vale já na próxima requisição do membro."""
    admin = await logado(sessoes, ("ADMIN_TI", GLOBAL))
    membro = await logado(sessoes)
    grupo = uuid7()
    diretorio.grupos[grupo] = frozenset({membro.user_id})
    antes = await cliente.get("/api/v1/me", headers=bearer(app, membro))
    assert antes.json()["papeis"] == []

    resposta = await cliente.post(
        ROTA, json=_corpo(grupo, "AUDITOR", "global", None), headers=bearer(app, admin)
    )
    assert resposta.status_code == 201

    depois = await cliente.get("/api/v1/me", headers=bearer(app, membro))
    [papel] = depois.json()["papeis"]
    assert (papel["codigo"], papel["origem"]) == ("AUDITOR", "grupo")


async def test_remover_mapeamento_remove_as_derivadas_e_mantem_as_diretas(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes, diretorio: DiretorioEmMemoria
) -> None:
    """003/R3.2 e R3.3: sem o mapeamento, as atribuições derivadas dele saem (auditadas como
    `papel.removido`), e a atribuição direta do mesmo papel fica."""
    admin = await logado(sessoes, ("ADMIN_TI", GLOBAL))
    membro = await logado(sessoes, ("AUDITOR", GLOBAL))
    grupo = uuid7()
    diretorio.grupos[grupo] = frozenset({membro.user_id})
    criado = await cliente.post(
        ROTA, json=_corpo(grupo, "AUDITOR", "global", None), headers=bearer(app, admin)
    )
    mapeamento = criado.json()["id"]
    assert [a["origin"] for a in await _atribuicoes_de(sessoes, membro.user_id)] == [
        "direct",
        "group",
    ]
    versao_antes = await _versao(sessoes, membro.user_id)

    resposta = await cliente.delete(f"{ROTA}/{mapeamento}", headers=bearer(app, admin))

    assert resposta.status_code == 204
    [direta] = await _atribuicoes_de(sessoes, membro.user_id)
    assert (direta["papel"], direta["origin"]) == ("AUDITOR", "direct")
    assert await _versao(sessoes, membro.user_id) == versao_antes + 1
    [removido] = await eventos(sessoes, "papel.removido")
    assert {m["campo"]: m["de"] for m in removido["changes"]}["mapeamento_id"] == mapeamento
    [evento] = await eventos(sessoes, "mapeamento.removido")
    assert (evento["entity_type"], evento["entity_id"]) == ("mapeamento_grupo", mapeamento)
    assert evento["actor_user_id"] == admin.user_id
    listagem = await cliente.get(ROTA, headers=bearer(app, admin))
    assert listagem.json()["total"] == 0


async def test_entrar_e_sair_do_grupo_adiciona_e_remove_a_derivada_sem_tocar_nas_diretas(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """003/R3.2 e R3.3: o recálculo do usuário cria a atribuição dos grupos mapeados em que ele
    entrou, remove a dos que deixou e não altera as diretas."""
    admin = await logado(sessoes, ("ADMIN_TI", GLOBAL))
    usuario = await logado(sessoes, ("DIRETORIA", GLOBAL))
    grupo, outro_grupo = uuid7(), uuid7()
    criado = await cliente.post(
        ROTA, json=_corpo(grupo, "AUDITOR", "global", None), headers=bearer(app, admin)
    )
    assert criado.status_code == 201
    mapeamento = criado.json()["id"]
    versao_antes = await _versao(sessoes, usuario.user_id)

    await _recalcular(sessoes, usuario.user_id, {grupo, outro_grupo})

    direta, derivada = await _atribuicoes_de(sessoes, usuario.user_id)
    assert (direta["papel"], direta["origin"]) == ("DIRETORIA", "direct")
    assert (derivada["papel"], derivada["origin"]) == ("AUDITOR", "group")
    assert str(derivada["group_mapping_id"]) == mapeamento
    assert await _versao(sessoes, usuario.user_id) == versao_antes + 1

    # Recalcular de novo, sem mudança, não duplica nem invalida o cache.
    await _recalcular(sessoes, usuario.user_id, {grupo})
    assert len(await _atribuicoes_de(sessoes, usuario.user_id)) == 2
    assert await _versao(sessoes, usuario.user_id) == versao_antes + 1

    await _recalcular(sessoes, usuario.user_id, set())

    [restante] = await _atribuicoes_de(sessoes, usuario.user_id)
    assert (restante["papel"], restante["origin"]) == ("DIRETORIA", "direct")
    assert await _versao(sessoes, usuario.user_id) == versao_antes + 2
    assert len(await eventos(sessoes, "papel.atribuido")) == 1
    [removido] = await eventos(sessoes, "papel.removido")
    assert {m["campo"]: m["de"] for m in removido["changes"]}["usuario_id"] == str(usuario.user_id)


async def test_listar_mapeamentos(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """003/R3: a listagem paginada mostra os mapeamentos criados."""
    admin = await logado(sessoes, ("ADMIN_TI", GLOBAL))
    grupo = uuid7()
    criado = await cliente.post(
        ROTA, json=_corpo(grupo, "AUDITOR", "global", None), headers=bearer(app, admin)
    )

    resposta = await cliente.get(ROTA, headers=bearer(app, admin))

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["total"] == 1
    assert corpo["itens"] == [criado.json()]


async def test_mapeamento_repetido_responde_409(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """003/R3.1: o mesmo grupo, papel e escopo não são mapeados duas vezes."""
    admin = bearer(app, await logado(sessoes, ("ADMIN_TI", GLOBAL)))
    corpo = _corpo(uuid7(), "AUDITOR", "global", None)
    assert (await cliente.post(ROTA, json=corpo, headers=admin)).status_code == 201

    resposta = await cliente.post(ROTA, json=corpo, headers=admin)

    assert resposta.status_code == 409


@pytest.mark.parametrize(
    ("papel", "tipo", "id_", "campo"),
    [
        ("INEXISTENTE", "global", None, "papel"),
        ("GESTOR_UNIDADE", "global", None, "escopo.tipo"),
        ("AUDITOR", "distrito", "1", "escopo.tipo"),
        ("TECNICO_DISTRITAL", "distrito", "32000", "escopo.id"),
        ("GESTOR_UNIDADE", "unidade", "nao-e-uuid", "escopo.id"),
    ],
)
async def test_papel_ou_escopo_invalido_responde_422(
    app: FastAPI,
    cliente: httpx.AsyncClient,
    sessoes: Sessoes,
    papel: str,
    tipo: str,
    id_: str | None,
    campo: str,
) -> None:
    """003/R3.1 com R2.1 e R2.2: o mapeamento obedece às regras de escopo da atribuição."""
    admin = bearer(app, await logado(sessoes, ("ADMIN_TI", GLOBAL)))

    resposta = await cliente.post(ROTA, json=_corpo(uuid7(), papel, tipo, id_), headers=admin)

    assert resposta.status_code == 422
    assert campo in {erro["campo"] for erro in resposta.json()["errors"]}


async def test_admin_membro_do_grupo_nao_cria_o_mapeamento(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes, diretorio: DiretorioEmMemoria
) -> None:
    """003/R3.1 com R2.5: mapear um grupo de que se é membro atribuiria papel a si mesmo."""
    admin = await logado(sessoes, ("ADMIN_TI", GLOBAL))
    grupo = uuid7()
    diretorio.grupos[grupo] = frozenset({admin.user_id})

    resposta = await cliente.post(
        ROTA, json=_corpo(grupo, "AUDITOR", "global", None), headers=bearer(app, admin)
    )

    assert resposta.status_code == 403
    assert [a["origin"] for a in await _atribuicoes_de(sessoes, admin.user_id)] == ["direct"]
    [negado] = await eventos(sessoes, "acesso.negado")
    assert negado["actor_user_id"] == admin.user_id


async def test_remover_mapeamento_inexistente_responde_404(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """003/R3: DELETE de mapeamento que não existe."""
    admin = bearer(app, await logado(sessoes, ("ADMIN_TI", GLOBAL)))

    assert (await cliente.delete(f"{ROTA}/{uuid7()}", headers=admin)).status_code == 404
    assert (await cliente.delete(f"{ROTA}/nao-e-uuid", headers=admin)).status_code == 422


@pytest.mark.parametrize(
    ("metodo", "caminho"),
    [("GET", ROTA), ("POST", ROTA), ("DELETE", f"{ROTA}/{uuid7()}")],
)
async def test_rotas_exigem_token_e_papel_assign(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes, metodo: str, caminho: str
) -> None:
    """003/R4.1 e R4.2: sem token, 401; sem `papel:assign`, 403."""
    corpo = _corpo(uuid7(), "AUDITOR", "global", None) if metodo == "POST" else None
    sem_token = await cliente.request(metodo, caminho, json=corpo)
    assert sem_token.status_code == 401

    gestor = bearer(app, await logado(sessoes, ("GESTOR_DADOS", GLOBAL)))
    sem_permissao = await cliente.request(metodo, caminho, json=corpo, headers=gestor)
    assert sem_permissao.status_code == 403
