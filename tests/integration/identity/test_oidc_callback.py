"""Rotas OIDC sobre o PostgreSQL, com um provedor falso no lugar do adaptador (004/T7).

Design da 004 § Rotas e § Fluxo, Login OIDC. O adaptador real (Authlib e PyJWT, a conferência do
`id_token`) tem os testes próprios em `tests/unit/identity/test_oidc_validacao.py`; aqui o
provedor falso devolve a identidade, ou a recusa, que o teste mandar.
"""

import base64
import hashlib
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import text

from src.main import create_app
from src.modules.identity.domain.oidc import MotivoDeRecusa, OidcIdentity, OidcRejected
from tests.factories import make_settings
from tests.integration.acesso import Sessoes, grupo_espelhado
from tests.integration.identity.autenticacao import usuario_local
from tests.integration.postgres import BancoDeTeste

FRONT = "https://sgs.teste/"
PROVEDOR = "https://provedor.teste/auth"
LOGIN = "/api/v1/auth/oidc/login"
CALLBACK = "/api/v1/auth/oidc/callback"
CODIGO = "codigo-do-provedor"


@dataclass
class ProvedorFalso:
    """`OidcPort` que guarda o que recebe e responde a identidade ou a recusa dada."""

    identidade: OidcIdentity | None = None
    recusa: MotivoDeRecusa | None = None
    pedidos: list[dict[str, str]] = field(default_factory=list)
    trocas: list[dict[str, str]] = field(default_factory=list)

    async def authorization_url(self, *, state: str, nonce: str, code_challenge: str) -> str:
        self.pedidos.append({"state": state, "nonce": nonce, "code_challenge": code_challenge})
        return f"{PROVEDOR}?{urlencode({'state': state, 'code_challenge': code_challenge})}"

    async def exchange(self, code: str, *, code_verifier: str, nonce: str) -> OidcIdentity:
        self.trocas.append({"code": code, "code_verifier": code_verifier, "nonce": nonce})
        if self.recusa is not None:
            raise OidcRejected(self.recusa)
        assert self.identidade is not None
        return self.identidade


def _identidade(**mudancas: Any) -> OidcIdentity:
    valores: dict[str, Any] = {
        "sub": "sub-ana",
        "username": "ana.oidc",
        "email": "ana@oidc.teste",
        "display_name": "Ana do Provedor",
        "groups": ("oidc-gestores",),
        "acr": None,
    }
    return OidcIdentity(**(valores | mudancas))


@pytest.fixture
def provedor() -> ProvedorFalso:
    return ProvedorFalso(identidade=_identidade())


@pytest.fixture
async def app(banco: BancoDeTeste, provedor: ProvedorFalso) -> AsyncIterator[FastAPI]:
    """O app de produção com o OIDC ligado, mas com o provedor falso no lugar do adaptador."""
    aplicacao = create_app(
        make_settings(
            database_url=SecretStr(banco.url_api),
            cors_origins=("https://sgs.teste",),
            oidc_issuer="https://provedor.teste/realms/sgs",
            oidc_client_id="sgs-api",
            oidc_client_secret=SecretStr("segredo-do-cliente-de-teste"),
            oidc_redirect_uri="https://sgs.teste/api/v1/auth/oidc/callback",
            frontend_url=FRONT,
        )
    )
    aplicacao.state.oidc = provedor
    yield aplicacao
    await aplicacao.state.engine.dispose()


async def _iniciar(cliente: httpx.AsyncClient) -> tuple[str, str]:
    """O navegador começa o login: devolve o `state` da URL do provedor e o cookie de vínculo."""
    resposta = await cliente.get(LOGIN)
    assert resposta.status_code == 302, resposta.text
    state = parse_qs(urlsplit(resposta.headers["location"]).query)["state"][0]
    return state, cliente.cookies["sgs_oidc"]


async def _voltar(cliente: httpx.AsyncClient, state: str, **extra: str) -> httpx.Response:
    return await cliente.get(CALLBACK, params={"code": CODIGO, "state": state} | extra)


async def _falhas(sessoes: Sessoes) -> list[dict[str, Any]]:
    async with sessoes() as sessao:
        linhas = await sessao.execute(
            text(
                "SELECT metadata, result, actor_type FROM audit_log"
                " WHERE action = 'auth.oidc_failed' ORDER BY id"
            )
        )
        return [dict(linha) for linha in linhas.mappings()]


async def _conta(sessoes: Sessoes, sub: str = "sub-ana") -> dict[str, Any] | None:
    async with sessoes() as sessao:
        linha = (
            (
                await sessao.execute(
                    text(
                        "SELECT id, username, email, display_name, is_active FROM users"
                        " WHERE source = 'oidc' AND external_id = :sub"
                    ),
                    {"sub": sub},
                )
            )
            .mappings()
            .one_or_none()
        )
    return None if linha is None else dict(linha)


def _recusado(resposta: httpx.Response) -> None:
    assert resposta.status_code == 302
    assert resposta.headers["location"] == f"{FRONT}?login_erro=oidc"
    assert "sgs_refresh" not in resposta.cookies
    assert "application/json" not in resposta.headers.get("content-type", "")


async def test_provedores_diz_o_que_esta_ligado(cliente: httpx.AsyncClient) -> None:
    """004/R3.9"""
    resposta = await cliente.get("/api/v1/auth/provedores")

    assert resposta.json() == {"ldap": False, "oidc": True}


async def test_login_redireciona_com_pkce_s256_e_cookie_de_vinculo(
    cliente: httpx.AsyncClient, sessoes: Sessoes, provedor: ProvedorFalso
) -> None:
    """004/R3.1, R3.8 (PKCE S256, `state`, `nonce`; cookie `HttpOnly; Secure; SameSite=Lax`
    no caminho do OIDC; `state` e vínculo só em hash no banco)"""
    resposta = await cliente.get(LOGIN)

    assert resposta.status_code == 302
    assert resposta.headers["location"].startswith(PROVEDOR)
    assert resposta.headers["cache-control"] == "no-store"
    assert resposta.headers["referrer-policy"] == "no-referrer"
    cookie = resposta.headers["set-cookie"]
    for atributo in ("HttpOnly", "Secure", "SameSite=lax", "Path=/api/v1/auth/oidc", "Max-Age=600"):
        assert atributo.lower() in cookie.lower()
    [pedido] = provedor.pedidos
    async with sessoes() as sessao:
        linha = (await sessao.execute(text("SELECT * FROM oidc_login_requests"))).mappings().one()
    assert linha["state_hash"] == hashlib.sha256(pedido["state"].encode()).hexdigest()
    assert linha["binding_hash"] == hashlib.sha256(cliente.cookies["sgs_oidc"].encode()).hexdigest()
    assert linha["nonce"] == pedido["nonce"]
    assert pedido["state"] not in str(dict(linha))


async def test_callback_provisiona_espelha_grupos_e_abre_a_sessao(
    cliente: httpx.AsyncClient, sessoes: Sessoes, provedor: ProvedorFalso
) -> None:
    """004/R3.2, R3.3, R3.4 (troca com o `code_verifier` do PKCE e o `nonce`; conta `oidc` com o
    `sub`; grupos `oidc`; 302 para o front só com o cookie de refresh; `amr = oidc`)"""
    async with sessoes() as sessao, sessao.begin():
        grupo = await grupo_espelhado(sessao)  # um grupo LDAP: não pode ser trocado pelo OIDC
    state, _ = await _iniciar(cliente)

    resposta = await _voltar(cliente, state)

    assert resposta.status_code == 302
    assert resposta.headers["location"] == FRONT
    assert "access_token" not in resposta.headers["location"]
    assert "sgs_refresh" in resposta.cookies
    [apagado] = [c for c in resposta.headers.get_list("set-cookie") if c.startswith("sgs_oidc=")]
    assert "max-age=0" in apagado.lower()
    [troca] = provedor.trocas
    desafio = base64.urlsafe_b64encode(hashlib.sha256(troca["code_verifier"].encode()).digest())
    assert desafio.rstrip(b"=").decode() == provedor.pedidos[0]["code_challenge"]
    assert troca["nonce"] == provedor.pedidos[0]["nonce"]
    assert troca["code"] == CODIGO
    conta = await _conta(sessoes)
    assert conta is not None
    assert (conta["username"], conta["email"], conta["is_active"]) == (
        "ana.oidc",
        "ana@oidc.teste",
        True,
    )
    async with sessoes() as sessao:
        grupos = (
            await sessao.execute(
                text(
                    "SELECT g.source, g.external_id FROM user_groups ug"
                    " JOIN groups g ON g.id = ug.group_id WHERE ug.user_id = :id"
                ),
                {"id": conta["id"]},
            )
        ).all()
        amr = await sessao.scalar(
            text("SELECT amr FROM sessions WHERE user_id = :id"), {"id": conta["id"]}
        )
        provisionado = await sessao.scalar(
            text("SELECT count(*) FROM audit_log WHERE action = 'usuario.provisionado'")
        )
    assert [tuple(g) for g in grupos] == [("oidc", "oidc-gestores")]
    assert amr == "oidc"
    assert provisionado == 1
    async with sessoes() as sessao:
        assert await sessao.scalar(
            text("SELECT is_active FROM groups WHERE id = :id"), {"id": grupo}
        )

    renovado = await cliente.post(
        "/api/v1/auth/refresh",
        headers={"X-Requested-With": "sgs", "Origin": "https://sgs.teste"},
    )
    assert renovado.status_code == 200, renovado.text


async def test_segundo_login_atualiza_a_conta_e_os_grupos(
    cliente: httpx.AsyncClient, sessoes: Sessoes, provedor: ProvedorFalso
) -> None:
    """004/R3.3 (atualiza nome e grupos pelo `sub`, sem conta nova)"""
    state, _ = await _iniciar(cliente)
    await _voltar(cliente, state)
    provedor.identidade = _identidade(display_name="Ana Renomeada", groups=("oidc-auditores",))

    state, _ = await _iniciar(cliente)
    resposta = await _voltar(cliente, state)

    assert resposta.headers["location"] == FRONT
    conta = await _conta(sessoes)
    assert conta is not None
    assert conta["display_name"] == "Ana Renomeada"
    async with sessoes() as sessao:
        grupos = (
            (
                await sessao.execute(
                    text(
                        "SELECT g.external_id FROM user_groups ug"
                        " JOIN groups g ON g.id = ug.group_id WHERE ug.user_id = :id"
                    ),
                    {"id": conta["id"]},
                )
            )
            .scalars()
            .all()
        )
        contas = await sessao.scalar(text("SELECT count(*) FROM users WHERE source = 'oidc'"))
    assert list(grupos) == ["oidc-auditores"]
    assert contas == 1


async def test_state_repetido_ou_desconhecido_e_recusado(
    cliente: httpx.AsyncClient, sessoes: Sessoes, provedor: ProvedorFalso
) -> None:
    """004/R3.7, R3.5 (uso único; `auth.oidc_failed` com o motivo; sem troca de código)"""
    state, _ = await _iniciar(cliente)
    await _voltar(cliente, state)

    repetido = await _voltar(cliente, state)
    desconhecido = await _voltar(cliente, "state-que-nunca-existiu")
    sem_state = await cliente.get(CALLBACK, params={"code": CODIGO})

    for resposta in (repetido, desconhecido, sem_state):
        _recusado(resposta)
    assert len(provedor.trocas) == 1
    falhas = await _falhas(sessoes)
    assert [f["metadata"]["motivo"] for f in falhas] == ["state", "state", "state"]
    assert {f["result"] for f in falhas} == {"failure"}


async def test_vinculo_de_outro_navegador_e_recusado_e_gasta_o_state(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes, provedor: ProvedorFalso
) -> None:
    """004/R3.7 (o `state` preso ao navegador pelo cookie; o `state` já fica usado)"""
    state, _ = await _iniciar(cliente)
    transporte = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transporte, base_url="https://teste") as outro:
        roubado = await _voltar(outro, state)

    depois = await _voltar(cliente, state)

    _recusado(roubado)
    _recusado(depois)
    assert provedor.trocas == []
    assert [f["metadata"]["motivo"] for f in await _falhas(sessoes)] == ["vinculo", "state"]


@pytest.mark.parametrize(
    ("motivo", "extra"),
    [
        pytest.param("erro_do_provedor", {"error": "access_denied"}, id="erro-do-provedor"),
        pytest.param("assinatura", {}, id="assinatura"),
        pytest.param("nonce", {}, id="nonce"),
        pytest.param("acr", {}, id="acr"),
    ],
)
async def test_recusa_da_troca_ou_do_provedor_redireciona_com_erro_generico(
    cliente: httpx.AsyncClient,
    sessoes: Sessoes,
    provedor: ProvedorFalso,
    motivo: str,
    extra: dict[str, str],
) -> None:
    """004/R3.2, R3.5, R3.6 (motivo auditado; nada provisionado)"""
    if not extra:
        provedor.recusa = motivo  # type: ignore[assignment]
    state, _ = await _iniciar(cliente)

    resposta = await _voltar(cliente, state, **extra)

    _recusado(resposta)
    assert [f["metadata"]["motivo"] for f in await _falhas(sessoes)] == [motivo]
    assert await _conta(sessoes) is None


async def test_conta_desativada_nao_entra_nem_e_reativada(
    cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """004/R4.4"""
    state, _ = await _iniciar(cliente)
    await _voltar(cliente, state)
    async with sessoes() as sessao, sessao.begin():
        await sessao.execute(
            text("UPDATE users SET is_active = false WHERE source = 'oidc' AND external_id = :s"),
            {"s": "sub-ana"},
        )

    state, _ = await _iniciar(cliente)
    resposta = await _voltar(cliente, state)

    _recusado(resposta)
    conta = await _conta(sessoes)
    assert conta is not None
    assert conta["is_active"] is False
    [falha] = await _falhas(sessoes)
    assert falha["metadata"] == {"motivo": "desativado", "sub": "sub-ana"}


@pytest.mark.parametrize(
    "campo", [pytest.param("username", id="username"), pytest.param("email", id="email")]
)
async def test_conflito_com_conta_de_outra_origem_recusa_sem_criar(
    cliente: httpx.AsyncClient, sessoes: Sessoes, provedor: ProvedorFalso, campo: str
) -> None:
    """004/R4.3 (nada é unido nem criado; conflito auditado)"""
    local = await usuario_local(sessoes, "ana.local")
    async with sessoes() as sessao, sessao.begin():
        await sessao.execute(
            text("UPDATE users SET email = 'ana.local@sgs.teste' WHERE id = :id"), {"id": local}
        )
    dados = {"username": "ana.local", "email": "ana.local@sgs.teste"}
    provedor.identidade = _identidade(**{campo: dados[campo]})
    state, _ = await _iniciar(cliente)

    resposta = await _voltar(cliente, state)

    _recusado(resposta)
    assert await _conta(sessoes) is None
    [falha] = await _falhas(sessoes)
    assert falha["metadata"] == {"motivo": "conflito_de_conta", "sub": "sub-ana"}


async def test_claim_de_grupos_grande_demais_e_recusada(
    cliente: httpx.AsyncClient, sessoes: Sessoes, provedor: ProvedorFalso
) -> None:
    """004/R3.3 (até 200 grupos, cada um até 255 caracteres; senão `claims`)"""
    provedor.identidade = _identidade(groups=tuple(f"g{i}" for i in range(201)))
    state, _ = await _iniciar(cliente)

    resposta = await _voltar(cliente, state)

    _recusado(resposta)
    assert [f["metadata"]["motivo"] for f in await _falhas(sessoes)] == ["claims"]
    assert await _conta(sessoes) is None


async def test_sem_oidc_as_rotas_respondem_404_e_provedores_diz_desligado(
    banco: BancoDeTeste,
) -> None:
    """004/R3.9 (sem OIDC_ISSUER, o OIDC fica desligado)"""
    aplicacao = create_app(make_settings(database_url=SecretStr(banco.url_api)))
    transporte = httpx.ASGITransport(app=aplicacao)
    try:
        async with httpx.AsyncClient(transport=transporte, base_url="https://teste") as cliente:
            login = await cliente.get(LOGIN)
            callback = await cliente.get(CALLBACK, params={"state": "x", "code": "y"})
            provedores = await cliente.get("/api/v1/auth/provedores")
    finally:
        await aplicacao.state.engine.dispose()

    assert (login.status_code, callback.status_code) == (404, 404)
    assert provedores.json() == {"ldap": False, "oidc": False}


async def test_login_tem_limite_por_ip(cliente: httpx.AsyncClient) -> None:
    """004 design § Rotas (20 por minuto por IP, instância própria do limite)"""
    respostas = [await cliente.get(LOGIN) for _ in range(21)]

    assert [r.status_code for r in respostas[:20]] == [302] * 20
    assert respostas[20].status_code == 429
