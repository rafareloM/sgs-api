"""`require()`, `CurrentUser`, `escopo_de_leitura` e `scope_filter` pela API (003/T4).

Design da 003 § Verificação e § Segurança; `CurrentUser` do design da 002 § Componentes.
As rotas protegidas aqui são de teste: o app de verdade ainda não tem rota com permissão.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

import httpx
import pytest
from fastapi import APIRouter, Depends, FastAPI, Request
from pydantic import SecretStr
from sqlalchemy import SmallInteger, Uuid, column, select, table, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.core.escopo import parametros_de_escopo, scope_filter
from src.core.ids import uuid7
from src.main import create_app
from src.modules.access.api.deps import ResourceRef, UsuarioAtual, require
from src.modules.access.application.autorizacao import escopo_de_leitura
from src.modules.access.domain.authorization import Alvo
from src.modules.identity.domain.sessions import AuthSession
from src.modules.identity.domain.tokens import TokenService
from src.modules.identity.infrastructure.repository import SqlSessionRepository, SqlUserRepository
from src.modules.identity.infrastructure.tokens import JwtTokenService
from tests.factories import make_auth_session, make_jwt_private_keys, make_settings, make_user
from tests.integration.postgres import BancoDeTeste, motor
from tests.integration.registry.cadastro import inserir_unidade

PROTEGIDA = "/api/v1/teste/protegida"

GLOBAL: tuple[str, str | None] = ("global", None)
SAUDE_MENTAL, SAUDE_BUCAL = 1, 2
DS_III, DS_IV = 3, 4

# Recursos de teste com os atributos de escopo de uma unidade (design § Verificação):
# nome → (id, distrito, área técnica).
RECURSOS: dict[str, tuple[UUID, int, int]] = {
    "caps_ds3": (UUID("01970000-0000-7000-8000-00000000000a"), DS_III, SAUDE_MENTAL),
    "caps_ds4": (UUID("01970000-0000-7000-8000-00000000000b"), DS_IV, SAUDE_MENTAL),
    "cbo_ds3": (UUID("01970000-0000-7000-8000-00000000000c"), DS_III, SAUDE_BUCAL),
}
TIPO_DE_TESTE = "recurso_de_teste"

recursos_de_teste = table(
    "recursos_de_teste",
    column("unit_id", Uuid),
    column("district_id", SmallInteger),
    column("technical_area_id", SmallInteger),
)

# Listagem escrita à mão com o fragmento fixo de escopo (design da 011 § Escopo em SQL explícito).
LISTAR_NO_ESCOPO = text("""
    SELECT unit_id FROM recursos_de_teste
    WHERE (:scope_global OR technical_area_id = ANY(CAST(:scope_areas AS smallint[]))
           OR district_id = ANY(CAST(:scope_districts AS smallint[]))
           OR unit_id = ANY(CAST(:scope_units AS uuid[])))
""")


# Id de distrito e de área técnica pelo código semeado na 0006 (spec 006).
ID_PELO_CODIGO = {
    "distrito": text("SELECT id FROM districts WHERE code = :codigo"),
    "area": text("SELECT id FROM technical_areas WHERE code = :codigo"),
}


class _AlvosDeTeste:
    """`ResolvedorDeAlvo` do recurso de teste, sobre a sessão que a dependência abre."""

    def __init__(self, sessao: AsyncSession) -> None:
        self._sessao = sessao

    async def alvo(self, id_do_recurso: str) -> Alvo | None:
        try:
            id_ = UUID(id_do_recurso)
        except ValueError:
            return None
        linha = (
            await self._sessao.execute(
                text(
                    "SELECT unit_id, district_id, technical_area_id FROM recursos_de_teste"
                    " WHERE unit_id = :id"
                ),
                {"id": id_},
            )
        ).one_or_none()
        if linha is None:
            return None
        unidade, distrito, area = linha
        return Alvo(unidade_id=unidade, distrito_id=distrito, area_id=area)


def _rotas_de_teste() -> APIRouter:
    rotas = APIRouter(prefix="/api/v1/teste")

    @rotas.get("/protegida", dependencies=[Depends(require("auditoria:read"))])
    async def protegida() -> dict[str, Any]:
        return {"ok": True}

    @rotas.get(
        "/recursos/{id}",
        dependencies=[Depends(require("unidade:update", ResourceRef(TIPO_DE_TESTE)))],
    )
    async def recurso(id: UUID) -> dict[str, Any]:
        return {"id": str(id)}

    @rotas.get(
        "/unidades/{id}",
        dependencies=[Depends(require("unidade:update", ResourceRef("unidade")))],
    )
    async def unidade(id: UUID) -> dict[str, Any]:
        return {"id": str(id)}

    @rotas.get("/recursos")
    async def listar(
        request: Request,
        usuario: Annotated[UsuarioAtual, Depends(require("auditoria:read"))],
        modo: Literal["scope_filter", "sql_explicito"],
    ) -> list[str]:
        escopo = escopo_de_leitura(usuario, "auditoria:read")
        async with request.app.state.sessoes() as sessao:
            if modo == "scope_filter":
                consulta = select(recursos_de_teste.c.unit_id).where(
                    scope_filter(escopo, recursos_de_teste)
                )
                ids = (await sessao.scalars(consulta)).all()
            else:
                ids = (await sessao.scalars(LISTAR_NO_ESCOPO, parametros_de_escopo(escopo))).all()
        return sorted(str(id_) for id_ in ids)

    return rotas


@pytest.fixture
async def app(banco: BancoDeTeste) -> AsyncIterator[FastAPI]:
    dono = motor(banco.url_dono)
    async with dono.begin() as conexao:
        await conexao.execute(
            text(
                "CREATE TABLE recursos_de_teste (unit_id uuid PRIMARY KEY,"
                " district_id smallint NOT NULL, technical_area_id smallint NOT NULL)"
            )
        )
        await conexao.execute(text("GRANT SELECT ON recursos_de_teste TO sgs_app"))
        await conexao.execute(
            text("INSERT INTO recursos_de_teste VALUES (:id, :distrito, :area)"),
            [{"id": i, "distrito": d, "area": a} for i, d, a in RECURSOS.values()],
        )
    await dono.dispose()

    app = create_app(make_settings(database_url=SecretStr(banco.url_api)))
    app.state.resolvedores_de_alvo[TIPO_DE_TESTE] = _AlvosDeTeste
    app.include_router(_rotas_de_teste())
    yield app
    await app.state.engine.dispose()


@pytest.fixture
async def sessoes(banco: BancoDeTeste) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Sessões com o login da API (papel sgs_app), para preparar os dados do teste."""
    engine = motor(banco.url_api)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def _novo_usuario(sessoes: async_sessionmaker[AsyncSession], *, ativo: bool = True) -> UUID:
    id_ = uuid7()
    usuario = make_user(id=id_, username=f"u{id_.hex}", email=None, is_active=ativo)
    async with sessoes() as sessao, sessao.begin():
        await SqlUserRepository(sessao).add(usuario)
    return usuario.id


async def _nova_sessao(
    sessoes: async_sessionmaker[AsyncSession], usuario: UUID, *, revogada: bool = False
) -> AuthSession:
    agora = datetime.now(UTC)
    sessao_de_login = make_auth_session(
        user_id=usuario, created_at=agora, revoked_at=agora if revogada else None
    )
    async with sessoes() as sessao, sessao.begin():
        await SqlSessionRepository(sessao).add(sessao_de_login)
    return sessao_de_login


async def _atribuir(
    sessoes: async_sessionmaker[AsyncSession],
    usuario: UUID,
    papel: str,
    escopo: tuple[str, str | None],
) -> None:
    async with sessoes() as sessao, sessao.begin():
        await sessao.execute(
            text(
                "INSERT INTO role_assignments (id, user_id, role_id, scope_type, scope_id, origin)"
                " SELECT :id, :usuario, id, :tipo, :id_do_escopo, 'direct'"
                " FROM roles WHERE code = :papel"
            ),
            {
                "id": uuid7(),
                "usuario": usuario,
                "tipo": escopo[0],
                "id_do_escopo": escopo[1],
                "papel": papel,
            },
        )


async def _logado(
    sessoes: async_sessionmaker[AsyncSession], *atribuicoes: tuple[str, tuple[str, str | None]]
) -> AuthSession:
    """Usuário ativo com os papéis dados e uma sessão de login aberta."""
    usuario = await _novo_usuario(sessoes)
    for papel, escopo in atribuicoes:
        await _atribuir(sessoes, usuario, papel, escopo)
    return await _nova_sessao(sessoes, usuario)


async def _acessos_negados(sessoes: async_sessionmaker[AsyncSession]) -> list[dict[str, Any]]:
    async with sessoes() as sessao:
        resultado = await sessao.execute(
            text(
                "SELECT actor_user_id, session_id, entity_type, entity_id, metadata"
                " FROM audit_log WHERE action = 'acesso.negado' ORDER BY id"
            )
        )
        return [dict(linha) for linha in resultado.mappings()]


def _bearer(app: FastAPI, sessao_de_login: AuthSession) -> dict[str, str]:
    tokens: TokenService = app.state.token_service
    return {"Authorization": f"Bearer {tokens.issue_access_token(sessao_de_login).token}"}


@pytest.fixture
async def cliente(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transporte = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transporte, base_url="http://teste") as cliente:
        yield cliente


async def test_sem_bearer_responde_401(cliente: httpx.AsyncClient) -> None:
    """002/R3.8, 003/R4.1: rota protegida sem `Authorization: Bearer` não passa."""
    resposta = await cliente.get(PROTEGIDA)

    assert resposta.status_code == 401
    assert resposta.headers["content-type"] == "application/problem+json"
    assert resposta.headers["www-authenticate"] == "Bearer"
    assert resposta.json()["title"] == "Não autenticado"


def _token_de_outra_chave() -> str:
    outra = JwtTokenService.from_settings(make_settings(jwt_private_keys=make_jwt_private_keys()))
    return outra.issue_access_token(make_auth_session()).token


@pytest.mark.parametrize(
    "token", ["nao-e-um-jwt", _token_de_outra_chave()], ids=["lixo", "outra-chave"]
)
async def test_token_invalido_responde_401(cliente: httpx.AsyncClient, token: str) -> None:
    """002/R3.8: assinatura inválida ou token mal formado."""
    resposta = await cliente.get(PROTEGIDA, headers={"Authorization": f"Bearer {token}"})

    assert resposta.status_code == 401
    assert resposta.headers["www-authenticate"] == "Bearer"
    assert resposta.json()["detail"] == "Token inválido ou expirado."


async def test_sessao_revogada_responde_401(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: async_sessionmaker[AsyncSession]
) -> None:
    """002/R3.8: o token ainda vale pela assinatura, mas a sessão dele foi revogada."""
    usuario = await _novo_usuario(sessoes)
    revogada = await _nova_sessao(sessoes, usuario, revogada=True)

    resposta = await cliente.get(PROTEGIDA, headers=_bearer(app, revogada))

    assert resposta.status_code == 401
    assert resposta.headers["www-authenticate"] == "Bearer"
    assert resposta.json()["detail"] == "Token inválido ou expirado."


async def test_usuario_desativado_responde_401(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: async_sessionmaker[AsyncSession]
) -> None:
    """002/R3.8 e design da 002 § Componentes: o `CurrentUser` só aceita usuário ativo."""
    usuario = await _novo_usuario(sessoes, ativo=False)
    sessao_de_login = await _nova_sessao(sessoes, usuario)

    resposta = await cliente.get(PROTEGIDA, headers=_bearer(app, sessao_de_login))

    assert resposta.status_code == 401
    assert resposta.json()["detail"] == "Token inválido ou expirado."


async def test_com_a_permissao_passa(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: async_sessionmaker[AsyncSession]
) -> None:
    """003/R4.2: `AUDITOR` tem `auditoria:read` (global)."""
    auditor = await _logado(sessoes, ("AUDITOR", GLOBAL))

    resposta = await cliente.get(PROTEGIDA, headers=_bearer(app, auditor))

    assert resposta.status_code == 200
    assert await _acessos_negados(sessoes) == []


async def test_sem_a_permissao_responde_403_e_audita_acesso_negado(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: async_sessionmaker[AsyncSession]
) -> None:
    """003/R4.2, 003/R4.6: `DIRETORIA` não tem `auditoria:read` em escopo nenhum."""
    diretoria = await _logado(sessoes, ("DIRETORIA", GLOBAL))

    resposta = await cliente.get(PROTEGIDA, headers=_bearer(app, diretoria))

    assert resposta.status_code == 403
    assert resposta.headers["content-type"] == "application/problem+json"
    assert resposta.json()["title"] == "Acesso negado"
    assert await _acessos_negados(sessoes) == [
        {
            "actor_user_id": diretoria.user_id,
            "session_id": diretoria.id,
            "entity_type": None,
            "entity_id": None,
            "metadata": {"permissao": "auditoria:read", "rota": "GET /api/v1/teste/protegida"},
        }
    ]


@pytest.mark.parametrize(
    ("papel", "escopo", "recurso", "status"),
    [
        ("GESTOR_UNIDADE", ("unidade", str(RECURSOS["caps_ds3"][0])), "caps_ds3", 200),
        ("GESTOR_UNIDADE", ("unidade", str(RECURSOS["caps_ds3"][0])), "caps_ds4", 403),
        ("TECNICO_DISTRITAL", ("distrito", str(DS_III)), "cbo_ds3", 200),
        ("TECNICO_DISTRITAL", ("distrito", str(DS_III)), "caps_ds4", 403),
        ("COORD_TECNICO", ("area", str(SAUDE_MENTAL)), "caps_ds4", 200),
        ("COORD_TECNICO", ("area", str(SAUDE_MENTAL)), "cbo_ds3", 403),
        ("GESTOR_DADOS", GLOBAL, "cbo_ds3", 200),
    ],
)
async def test_recurso_so_passa_dentro_de_algum_escopo_da_permissao(
    app: FastAPI,
    cliente: httpx.AsyncClient,
    sessoes: async_sessionmaker[AsyncSession],
    papel: str,
    escopo: tuple[str, str | None],
    recurso: str,
    status: int,
) -> None:
    """003/R4.3: escopo `Unidade`, `Distrito`, `Area` ou `Global` que cubra o recurso."""
    sessao_de_login = await _logado(sessoes, (papel, escopo))

    resposta = await cliente.get(
        f"/api/v1/teste/recursos/{RECURSOS[recurso][0]}", headers=_bearer(app, sessao_de_login)
    )

    assert resposta.status_code == status


async def test_fora_do_escopo_responde_403_e_audita_o_recurso(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: async_sessionmaker[AsyncSession]
) -> None:
    """003/R4.3, 003/R4.6; design § Segurança: 403, e não 404, para recurso fora do escopo."""
    gestor = await _logado(sessoes, ("GESTOR_UNIDADE", ("unidade", str(RECURSOS["caps_ds3"][0]))))
    outra_unidade = RECURSOS["caps_ds4"][0]

    resposta = await cliente.get(
        f"/api/v1/teste/recursos/{outra_unidade}", headers=_bearer(app, gestor)
    )

    assert resposta.status_code == 403
    assert resposta.json()["title"] == "Acesso negado"
    assert await _acessos_negados(sessoes) == [
        {
            "actor_user_id": gestor.user_id,
            "session_id": gestor.id,
            "entity_type": TIPO_DE_TESTE,
            "entity_id": str(outra_unidade),
            "metadata": {"permissao": "unidade:update", "rota": "GET /api/v1/teste/recursos/{id}"},
        }
    ]


async def test_sem_a_permissao_em_escopo_nenhum_nem_procura_o_recurso(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: async_sessionmaker[AsyncSession]
) -> None:
    """003/R4.2: sem a permissão, 403 mesmo para recurso inexistente (não revela se existe)."""
    auditor = await _logado(sessoes, ("AUDITOR", GLOBAL))

    resposta = await cliente.get(f"/api/v1/teste/recursos/{uuid7()}", headers=_bearer(app, auditor))

    assert resposta.status_code == 403


async def test_recurso_inexistente_responde_404_a_quem_tem_a_permissao(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: async_sessionmaker[AsyncSession]
) -> None:
    """003/R4.3: sem recurso não há escopo a conferir (padrão em "Perguntas em aberto")."""
    tecnico = await _logado(sessoes, ("TECNICO_DISTRITAL", ("distrito", str(DS_III))))

    resposta = await cliente.get(f"/api/v1/teste/recursos/{uuid7()}", headers=_bearer(app, tecnico))

    assert resposta.status_code == 404
    assert await _acessos_negados(sessoes) == []


def _ids(*nomes: str) -> list[str]:
    return sorted(str(RECURSOS[nome][0]) for nome in nomes)


@pytest.mark.parametrize("modo", ["scope_filter", "sql_explicito"])
@pytest.mark.parametrize(
    ("atribuicoes", "esperado"),
    [
        ([("AUDITOR", GLOBAL)], _ids("caps_ds3", "caps_ds4", "cbo_ds3")),
        ([("TECNICO_DISTRITAL", ("distrito", str(DS_III)))], _ids("caps_ds3", "cbo_ds3")),
        ([("COORD_TECNICO", ("area", str(SAUDE_MENTAL)))], _ids("caps_ds3", "caps_ds4")),
        ([("GESTOR_UNIDADE", ("unidade", str(RECURSOS["caps_ds4"][0])))], _ids("caps_ds4")),
        (
            [
                ("COORD_TECNICO", ("area", str(SAUDE_BUCAL))),
                ("GESTOR_UNIDADE", ("unidade", str(RECURSOS["caps_ds4"][0]))),
            ],
            _ids("caps_ds4", "cbo_ds3"),
        ),
    ],
    ids=["global", "distrito", "area", "unidade", "area-e-unidade"],
)
async def test_listagem_devolve_so_o_que_esta_no_escopo_de_leitura(
    app: FastAPI,
    cliente: httpx.AsyncClient,
    sessoes: async_sessionmaker[AsyncSession],
    atribuicoes: list[tuple[str, tuple[str, str | None]]],
    esperado: list[str],
    modo: str,
) -> None:
    """003/R4.4: `scope_filter` (SQLAlchemy) e `escopo_de_leitura` no fragmento fixo da 011."""
    sessao_de_login = await _logado(sessoes, *atribuicoes)

    resposta = await cliente.get(
        "/api/v1/teste/recursos", params={"modo": modo}, headers=_bearer(app, sessao_de_login)
    )

    assert resposta.status_code == 200
    assert resposta.json() == esperado


@pytest.mark.parametrize(
    ("papel", "escopo", "unidade", "status"),
    [
        ("TECNICO_DISTRITAL", ("distrito", "DS-III"), "caps_ds3", 200),
        ("TECNICO_DISTRITAL", ("distrito", "DS-III"), "caps_ds4", 403),
        ("COORD_TECNICO", ("area", "SAUDE_MENTAL"), "caps_ds4", 200),
        ("COORD_TECNICO", ("area", "SAUDE_MENTAL"), "usf_ds3", 403),
        ("GESTOR_UNIDADE", ("unidade", "caps_ds3"), "caps_ds3", 200),
        ("GESTOR_UNIDADE", ("unidade", "caps_ds3"), "usf_ds3", 403),
    ],
)
async def test_unidade_resolve_distrito_e_area_tecnica_pelo_tipo(
    app: FastAPI,
    cliente: httpx.AsyncClient,
    sessoes: async_sessionmaker[AsyncSession],
    banco: BancoDeTeste,
    papel: str,
    escopo: tuple[str, str],
    unidade: str,
    status: int,
) -> None:
    """003/R4.3: `ResourceRef("unidade")` dá o id, o distrito e a área do tipo da unidade."""
    dono = motor(banco.url_dono)
    async with dono.begin() as conexao:
        unidades = {
            "caps_ds3": await inserir_unidade(conexao, "CAPS III", distrito="DS-III"),
            "caps_ds4": await inserir_unidade(conexao, "CAPS IV", distrito="DS-IV"),
            "usf_ds3": await inserir_unidade(conexao, "USF III", distrito="DS-III", tipo="USF"),
        }
        if escopo[0] == "unidade":
            id_do_escopo = str(unidades[escopo[1]])
        else:
            id_do_escopo = str(
                await conexao.scalar(ID_PELO_CODIGO[escopo[0]], {"codigo": escopo[1]})
            )
    await dono.dispose()
    sessao_de_login = await _logado(sessoes, (papel, (escopo[0], id_do_escopo)))

    resposta = await cliente.get(
        f"/api/v1/teste/unidades/{unidades[unidade]}", headers=_bearer(app, sessao_de_login)
    )

    assert resposta.status_code == status
