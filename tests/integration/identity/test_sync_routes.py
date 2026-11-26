"""Rotas da sincronização, das execuções e dos grupos (004/T4; design § Rotas).

O diretório é um `DirectoryPort` falso em `app.state.diretorio`. A tarefa em segundo plano roda
dentro da chamada do `httpx.ASGITransport`, então a execução já está fechada quando a resposta
chega ao teste.
"""

from typing import Any
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text

from src.core.ids import uuid7
from src.modules.identity.domain.diretorio import (
    DirectoryGroup,
    DirectorySnapshot,
    DirectoryUser,
)
from tests.integration.acesso import GLOBAL, Sessoes, bearer, eventos, logado

BASE = "/api/v1/admin/diretorio"
ANA = DirectoryUser(
    external_id="uuid-ana",
    dn="uid=ana,dc=recife",
    login="ana",
    email="ana@recife.pe.gov.br",
    display_name="Ana",
)
BRUNO = DirectoryUser(
    external_id="uuid-bruno", dn="uid=bruno,dc=recife", login="bruno", email=None, display_name="B"
)


def _grupo(nome: str, *membros: DirectoryUser) -> DirectoryGroup:
    return DirectoryGroup(
        external_id=f"uuid-{nome}",
        dn=f"cn={nome},dc=recife",
        name=nome,
        member_dns=frozenset(m.dn for m in membros),
    )


class DiretorioFalso:
    def __init__(self) -> None:
        self.retrato = DirectorySnapshot(
            users=(ANA, BRUNO),
            groups=(_grupo("Vigilância", ANA, BRUNO), _grupo("ti", ANA)),
        )

    async def snapshot(self) -> DirectorySnapshot:
        return self.retrato

    async def find_user(self, login: str) -> DirectoryUser | None:  # pragma: no cover
        raise NotImplementedError

    async def verify_password(self, dn: str, password: str) -> bool:  # pragma: no cover
        raise NotImplementedError

    async def groups_of(
        self, user: DirectoryUser
    ) -> tuple[DirectoryGroup, ...]:  # pragma: no cover
        raise NotImplementedError


@pytest.fixture
def diretorio(app: FastAPI) -> DiretorioFalso:
    falso = DiretorioFalso()
    app.state.diretorio = falso
    return falso


@pytest.fixture
async def admin(app: FastAPI, sessoes: Sessoes) -> dict[str, str]:
    return bearer(app, await logado(sessoes, ("ADMIN_TI", GLOBAL)))


async def _sincronizar(cliente: httpx.AsyncClient, cabecalhos: dict[str, str]) -> httpx.Response:
    return await cliente.post(f"{BASE}/sincronizar", headers=cabecalhos)


async def test_disparo_responde_202_e_a_execucao_fica_consultavel(
    app: FastAPI,
    cliente: httpx.AsyncClient,
    sessoes: Sessoes,
    diretorio: DiretorioFalso,
    admin: dict[str, str],
) -> None:
    """004/R1.1, R1.9"""
    resposta = await _sincronizar(cliente, admin)

    assert resposta.status_code == 202
    corpo = resposta.json()
    assert corpo["status"] == "em_andamento"
    execucao = corpo["execucao_id"]

    detalhe = await cliente.get(f"{BASE}/execucoes/{execucao}", headers=admin)
    assert detalhe.status_code == 200
    dados = detalhe.json()
    assert dados["id"] == execucao
    assert dados["tipo"] == "ldap"
    assert dados["status"] == "concluida"
    assert dados["usuarios"] == {"criados": 2, "atualizados": 0, "desativados": 0}
    assert dados["grupos"] == {"criados": 2, "atualizados": 0, "desativados": 0}
    assert dados["conflitos"] == []
    assert dados["erro"] is None
    assert dados["disparada_por"] is not None
    assert dados["concluida_em"] is not None

    [evento] = await eventos(sessoes, "diretorio.sincronizado")
    assert str(evento["actor_user_id"]) == dados["disparada_por"]


async def test_segunda_execucao_em_andamento_responde_409(
    cliente: httpx.AsyncClient,
    sessoes: Sessoes,
    diretorio: DiretorioFalso,
    admin: dict[str, str],
) -> None:
    """004/R1.11"""
    async with sessoes() as sessao, sessao.begin():
        await sessao.execute(
            text(
                "INSERT INTO directory_sync_runs (id, kind, status, started_at)"
                " VALUES (:id, 'ldap', 'em_andamento', now())"
            ),
            {"id": uuid7()},
        )

    resposta = await _sincronizar(cliente, admin)

    assert resposta.status_code == 409
    [falha] = await eventos(sessoes, "operacao.falhou")
    assert falha["metadata"]["status"] == 409


async def test_sem_ldap_configurado_responde_503(
    app: FastAPI, cliente: httpx.AsyncClient, admin: dict[str, str]
) -> None:
    """004/R1.1 (design § Rotas: 503 sem LDAP_URL)"""
    app.state.diretorio = None

    assert (await _sincronizar(cliente, admin)).status_code == 503


async def test_execucoes_da_mais_recente_para_a_mais_antiga_e_paginadas(
    cliente: httpx.AsyncClient, diretorio: DiretorioFalso, admin: dict[str, str]
) -> None:
    """004/R1.9"""
    ids = [(await _sincronizar(cliente, admin)).json()["execucao_id"] for _ in range(3)]

    pagina = await cliente.get(f"{BASE}/execucoes", params={"tamanho": 2}, headers=admin)

    assert pagina.status_code == 200
    corpo = pagina.json()
    assert corpo["total"] == 3
    assert [e["id"] for e in corpo["itens"]] == [ids[2], ids[1]]
    segunda = await cliente.get(
        f"{BASE}/execucoes", params={"tamanho": 2, "pagina": 2}, headers=admin
    )
    assert [e["id"] for e in segunda.json()["itens"]] == [ids[0]]


async def test_execucao_inexistente_responde_404(
    cliente: httpx.AsyncClient, admin: dict[str, str]
) -> None:
    """004/R1.9"""
    resposta = await cliente.get(f"{BASE}/execucoes/{uuid7()}", headers=admin)

    assert resposta.status_code == 404


async def test_grupos_com_membros_ativos_e_filtros(
    cliente: httpx.AsyncClient,
    sessoes: Sessoes,
    diretorio: DiretorioFalso,
    admin: dict[str, str],
) -> None:
    """004/R1.14 (id, origem, nome, membros ativos; `ativo` padrão `true`; busca no nome)"""
    await _sincronizar(cliente, admin)
    async with sessoes() as sessao, sessao.begin():
        await sessao.execute(text("UPDATE users SET is_active = false WHERE username = 'bruno'"))
    diretorio.retrato = DirectorySnapshot(
        users=(ANA, BRUNO), groups=(_grupo("Vigilância", ANA, BRUNO),)
    )
    await _sincronizar(cliente, admin)  # "ti" desativado

    ativos = await cliente.get(f"{BASE}/grupos", headers=admin)

    assert ativos.status_code == 200
    corpo = ativos.json()
    assert corpo["total"] == 1
    [vigilancia] = corpo["itens"]
    assert (vigilancia["nome"], vigilancia["origem"], vigilancia["ativo"]) == (
        "Vigilância",
        "ldap",
        True,
    )
    # A sincronização reativou o bruno; desativado de novo, ele não conta.
    async with sessoes() as sessao, sessao.begin():
        await sessao.execute(text("UPDATE users SET is_active = false WHERE username = 'bruno'"))
    vigilancia = (await cliente.get(f"{BASE}/grupos", headers=admin)).json()["itens"][0]
    assert vigilancia["membros_ativos"] == 1
    UUID(vigilancia["id"])

    inativos = (
        await cliente.get(f"{BASE}/grupos", params={"ativo": "false"}, headers=admin)
    ).json()
    assert [g["nome"] for g in inativos["itens"]] == ["ti"]
    busca = await cliente.get(f"{BASE}/grupos", params={"busca": "VIGIL"}, headers=admin)
    assert [g["nome"] for g in busca.json()["itens"]] == ["Vigilância"]
    nada = await cliente.get(f"{BASE}/grupos", params={"origem": "oidc"}, headers=admin)
    assert nada.json()["total"] == 0


async def test_mapear_grupo_atribui_o_papel_aos_membros_ativos_de_user_groups(
    app: FastAPI,
    cliente: httpx.AsyncClient,
    sessoes: Sessoes,
    diretorio: DiretorioFalso,
    admin: dict[str, str],
) -> None:
    """004/R1.14; 003/R3.1 (o `SemMembrosDeGrupo` deu lugar à leitura de `user_groups`)"""
    await _sincronizar(cliente, admin)
    async with sessoes() as sessao, sessao.begin():
        await sessao.execute(text("UPDATE users SET is_active = false WHERE username = 'bruno'"))
    [grupo] = [
        g
        for g in (await cliente.get(f"{BASE}/grupos", headers=admin)).json()["itens"]
        if g["nome"] == "Vigilância"
    ]

    resposta = await cliente.post(
        "/api/v1/admin/mapeamentos-grupo",
        json={"grupo_id": grupo["id"], "papel": "AUDITOR", "escopo_tipo": "global"},
        headers=admin,
    )

    assert resposta.status_code == 201
    async with sessoes() as sessao:
        donos = list(
            await sessao.scalars(
                text(
                    "SELECT u.username FROM role_assignments ra JOIN users u ON u.id = ra.user_id"
                    " WHERE ra.origin = 'group'"
                )
            )
        )
    assert donos == ["ana"]


@pytest.mark.parametrize(
    ("metodo", "caminho"),
    [
        ("POST", f"{BASE}/sincronizar"),
        ("GET", f"{BASE}/execucoes"),
        ("GET", f"{BASE}/execucoes/{uuid7()}"),
        ("GET", f"{BASE}/grupos"),
    ],
)
async def test_sem_token_responde_401(
    cliente: httpx.AsyncClient, metodo: str, caminho: str
) -> None:
    """004 design § Rotas (deny by default)"""
    assert (await cliente.request(metodo, caminho)).status_code == 401


@pytest.mark.parametrize(
    ("metodo", "caminho"),
    [
        ("POST", f"{BASE}/sincronizar"),
        ("GET", f"{BASE}/execucoes"),
        ("GET", f"{BASE}/execucoes/{uuid7()}"),
        ("GET", f"{BASE}/grupos"),
    ],
)
async def test_sem_permissao_responde_403(
    app: FastAPI,
    cliente: httpx.AsyncClient,
    sessoes: Sessoes,
    diretorio: DiretorioFalso,
    metodo: str,
    caminho: str,
) -> None:
    """004 design § Rotas (`diretorio:sync` e `papel:assign` só do ADMIN_TI)"""
    auditor = bearer(app, await logado(sessoes, ("AUDITOR", GLOBAL)))

    assert (await cliente.request(metodo, caminho, headers=auditor)).status_code == 403


@pytest.mark.parametrize(
    ("caminho", "parametros"),
    [
        ("execucoes", {"tamanho": "0"}),
        ("execucoes", {"pagina": "0"}),
        ("execucoes/nao-e-uuid", {}),
        ("grupos", {"origem": "local"}),
        ("grupos", {"busca": "x" * 101}),
        ("grupos", {"tamanho": "101"}),
    ],
)
async def test_parametro_invalido_responde_422(
    cliente: httpx.AsyncClient, admin: dict[str, str], caminho: str, parametros: dict[str, Any]
) -> None:
    """004 design § Rotas"""
    resposta = await cliente.get(f"{BASE}/{caminho}", params=parametros, headers=admin)

    assert resposta.status_code == 422
