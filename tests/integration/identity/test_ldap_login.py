"""`POST /auth/login` com `provider = "ldap"` (004/T5; design § Fluxo, Login LDAP).

O diretório é um `DirectoryPort` falso em `app.state.diretorio`; banco, 2FA, auditoria e o
recálculo das derivadas da 003 são os de verdade.
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
    DirectoryUnavailable,
    DirectoryUser,
)
from src.modules.identity.domain.users import User, UserSource
from src.modules.identity.infrastructure.repository import SqlUserRepository
from tests.factories import make_user
from tests.integration.acesso import GLOBAL, Sessoes, bearer, eventos, logado
from tests.integration.identity.autenticacao import codigo, segredo_da_uri, usuario_local

SENHA_LDAP = "senha-do-diretorio-123"
ANA = DirectoryUser(
    external_id="uuid-ana",
    dn="uid=ana,ou=pessoas,dc=recife",
    login="ana",
    email="ana@recife.pe.gov.br",
    display_name="Ana Souza",
)
TI = DirectoryGroup(
    external_id="uuid-ti", dn="cn=ti,ou=grupos,dc=recife", name="ti", member_dns=frozenset()
)


class DiretorioFalso:
    """`DirectoryPort` em memória, que conta as buscas e os *binds*."""

    def __init__(self) -> None:
        self.usuarios: dict[str, DirectoryUser] = {ANA.login: ANA}
        self.senhas: dict[str, str] = {ANA.dn: SENHA_LDAP}
        self.grupos: dict[str, tuple[DirectoryGroup, ...]] = {ANA.dn: (TI,)}
        self.fora = False
        self.buscas = 0
        self.binds = 0

    def _conferir(self) -> None:
        if self.fora:
            raise DirectoryUnavailable("Serviço de diretório indisponível")

    async def snapshot(self) -> DirectorySnapshot:  # pragma: no cover - só a sincronização
        raise NotImplementedError

    async def find_user(self, login: str) -> DirectoryUser | None:
        self.buscas += 1
        self._conferir()
        return self.usuarios.get(login)

    async def verify_password(self, dn: str, password: str) -> bool:
        self.binds += 1
        self._conferir()
        return bool(password) and self.senhas.get(dn) == password

    async def groups_of(self, user: DirectoryUser) -> tuple[DirectoryGroup, ...]:
        self._conferir()
        return self.grupos.get(user.dn, ())


@pytest.fixture
def diretorio(app: FastAPI) -> DiretorioFalso:
    falso = DiretorioFalso()
    app.state.diretorio = falso
    return falso


async def _login(
    cliente: httpx.AsyncClient, username: str, senha: str = SENHA_LDAP, provider: str = "ldap"
) -> httpx.Response:
    return await cliente.post(
        "/api/v1/auth/login",
        json={"username": username, "password": senha, "provider": provider},
    )


async def _conta(sessoes: Sessoes, external_id: str) -> dict[str, Any] | None:
    async with sessoes() as sessao:
        linha = (
            (
                await sessao.execute(
                    text(
                        "SELECT id, username, email, display_name, is_active, synced_at,"
                        " failed_logins, locked_until FROM users"
                        " WHERE source = 'ldap' AND external_id = :ext"
                    ),
                    {"ext": external_id},
                )
            )
            .mappings()
            .one_or_none()
        )
    return None if linha is None else dict(linha)


async def _conta_ldap(sessoes: Sessoes, *, ativo: bool = True, **campos: Any) -> UUID:
    usuario = User(
        id=uuid7(),
        username=campos.get("username", ANA.login),
        display_name=campos.get("display_name", "Nome Antigo"),
        source=UserSource.LDAP,
        email=campos.get("email", "antigo@recife.pe.gov.br"),
        external_id=ANA.external_id,
        is_active=ativo,
    )
    async with sessoes() as sessao, sessao.begin():
        await SqlUserRepository(sessao).add(usuario)
    return usuario.id


async def _motivos(sessoes: Sessoes) -> list[str]:
    return [e["metadata"].get("motivo") for e in await eventos(sessoes, "auth.login_failed")]


async def test_bind_certo_provisiona_a_conta_os_grupos_e_pede_o_2fa(
    cliente: httpx.AsyncClient, sessoes: Sessoes, diretorio: DiretorioFalso
) -> None:
    """004/R2.1, R2.3"""
    resposta = await _login(cliente, "ANA")

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["mfa_enrollment_required"] is True
    assert corpo["mfa_token"]
    assert corpo["access_token"] is None
    conta = await _conta(sessoes, ANA.external_id)
    assert conta is not None
    assert (conta["username"], conta["email"], conta["display_name"]) == (
        "ana",
        "ana@recife.pe.gov.br",
        "Ana Souza",
    )
    assert conta["synced_at"] is not None
    async with sessoes() as sessao:
        grupos = list(
            await sessao.scalars(
                text(
                    "SELECT g.name FROM user_groups ug JOIN groups g ON g.id = ug.group_id"
                    " WHERE ug.user_id = :id AND ug.source = 'ldap'"
                ),
                {"id": conta["id"]},
            )
        )
    assert grupos == ["ti"]
    [provisionado] = await eventos(sessoes, "usuario.provisionado")
    assert provisionado["entity_id"] == str(conta["id"])
    assert provisionado["metadata"] == {"origem": "ldap"}


async def test_2fa_do_usuario_ldap_abre_sessao_com_amr_ldap_otp(
    cliente: httpx.AsyncClient, sessoes: Sessoes, diretorio: DiretorioFalso
) -> None:
    """004/R2.3; D004-16"""
    desafio = (await _login(cliente, "ana")).json()["mfa_token"]
    uri = (await cliente.post("/api/v1/auth/mfa/enroll", json={"mfa_token": desafio})).json()[
        "otpauth_uri"
    ]
    confirmado = await cliente.post(
        "/api/v1/auth/mfa/confirm",
        json={"mfa_token": desafio, "code": codigo(segredo_da_uri(uri))},
    )

    assert confirmado.status_code == 200
    [entrou] = await eventos(sessoes, "auth.login")
    assert entrou["metadata"]["amr"] == "ldap+otp"
    async with sessoes() as sessao:
        amr = await sessao.scalar(text("SELECT amr FROM sessions"))
    assert amr == "ldap+otp"


async def test_conta_existente_e_atualizada_pelo_diretorio(
    cliente: httpx.AsyncClient, sessoes: Sessoes, diretorio: DiretorioFalso
) -> None:
    """004/R2.3 (nome e e-mail do diretório, `synced_at`)"""
    await _conta_ldap(sessoes)

    resposta = await _login(cliente, "ana")

    assert resposta.status_code == 200
    conta = await _conta(sessoes, ANA.external_id)
    assert conta is not None
    assert (conta["display_name"], conta["email"]) == ("Ana Souza", "ana@recife.pe.gov.br")
    assert conta["synced_at"] is not None
    assert await eventos(sessoes, "usuario.provisionado") == []


async def test_senha_errada_e_usuario_fora_do_diretorio_dao_o_mesmo_401(
    cliente: httpx.AsyncClient, sessoes: Sessoes, diretorio: DiretorioFalso
) -> None:
    """004/R2.1 (mensagem genérica da 002/R1.3)"""
    errada = await _login(cliente, "ana", "senha-errada")
    inexistente = await _login(cliente, "ninguem")

    assert errada.status_code == inexistente.status_code == 401
    assert errada.json()["detail"] == inexistente.json()["detail"]
    assert await _conta(sessoes, ANA.external_id) is None


async def test_cinco_falhas_bloqueiam_e_o_bloqueio_vem_antes_do_bind(
    cliente: httpx.AsyncClient, sessoes: Sessoes, diretorio: DiretorioFalso
) -> None:
    """004/R2.1; 002/R1.4 (design § Segurança: bloqueio conferido antes do *bind*)"""
    await _conta_ldap(sessoes)
    for _ in range(5):
        assert (await _login(cliente, "ana", "senha-errada")).status_code == 401
    binds = diretorio.binds

    bloqueado = await _login(cliente, "ana")

    assert bloqueado.status_code == 401
    assert diretorio.binds == binds
    conta = await _conta(sessoes, ANA.external_id)
    assert conta is not None
    assert conta["locked_until"] is not None
    assert "bloqueado" in await _motivos(sessoes)


async def test_conta_de_outra_origem_nao_entra_por_ldap_nem_a_ldap_pela_senha_local(
    cliente: httpx.AsyncClient, sessoes: Sessoes, diretorio: DiretorioFalso
) -> None:
    """004/R4.1 (nos dois sentidos)"""
    await usuario_local(sessoes, "ana")

    por_ldap = await _login(cliente, "ana")

    assert por_ldap.status_code == 401
    assert diretorio.buscas == 0

    diretorio.usuarios["bia"] = DirectoryUser(
        external_id="uuid-bia", dn="uid=bia,dc=recife", login="bia", email=None, display_name="Bia"
    )
    diretorio.senhas["uid=bia,dc=recife"] = SENHA_LDAP
    assert (await _login(cliente, "bia")).status_code == 200
    assert (await _login(cliente, "bia", provider="local")).status_code == 401


async def test_conflito_de_email_recusa_sem_criar_conta(
    cliente: httpx.AsyncClient, sessoes: Sessoes, diretorio: DiretorioFalso
) -> None:
    """004/R4.3"""
    outra = make_user(username="ana.local", email=ANA.email)
    async with sessoes() as sessao, sessao.begin():
        await SqlUserRepository(sessao).add(outra)

    resposta = await _login(cliente, "ana")

    assert resposta.status_code == 401
    assert await _conta(sessoes, ANA.external_id) is None
    assert "conflito_de_conta" in await _motivos(sessoes)
    assert await eventos(sessoes, "usuario.provisionado") == []


async def test_conta_inativa_e_recusada_e_nao_e_reativada(
    cliente: httpx.AsyncClient, sessoes: Sessoes, diretorio: DiretorioFalso
) -> None:
    """004/R4.4"""
    await _conta_ldap(sessoes, ativo=False)

    resposta = await _login(cliente, "ana")

    assert resposta.status_code == 401
    conta = await _conta(sessoes, ANA.external_id)
    assert conta is not None
    assert conta["is_active"] is False
    assert "desativado" in await _motivos(sessoes)


async def test_diretorio_fora_responde_503_e_audita(
    cliente: httpx.AsyncClient, sessoes: Sessoes, diretorio: DiretorioFalso
) -> None:
    """004/R2.1 (design § Fluxo, Login LDAP: `DirectoryUnavailable` vira 503)"""
    diretorio.fora = True

    resposta = await _login(cliente, "ana")

    assert resposta.status_code == 503
    assert resposta.json()["detail"] == "Serviço de diretório indisponível"
    assert await _motivos(sessoes) == ["diretorio_indisponivel"]


async def test_sem_ldap_configurado_responde_503(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """004/R2.1 (sem LDAP_URL não há diretório para o *bind*)"""
    app.state.diretorio = None

    resposta = await _login(cliente, "ana")

    assert resposta.status_code == 503


async def test_provider_fora_da_lista_e_422(
    cliente: httpx.AsyncClient, diretorio: DiretorioFalso
) -> None:
    """004/R2.1 (`provider` é `local` ou `ldap`)"""
    assert (await _login(cliente, "ana", provider="oidc")).status_code == 422


async def test_senha_vazia_nao_chega_ao_diretorio(
    cliente: httpx.AsyncClient, diretorio: DiretorioFalso
) -> None:
    """004/R2.4"""
    resposta = await _login(cliente, "ana", senha="")

    assert resposta.status_code in {401, 422}
    assert diretorio.buscas == diretorio.binds == 0


async def test_login_renomeado_no_diretorio_conta_falhas_e_bloqueia_a_mesma_conta(
    cliente: httpx.AsyncClient, sessoes: Sessoes, diretorio: DiretorioFalso
) -> None:
    """004/R2.1; 002/R1.4 (a conta é a do `external_id`, mesmo com o `username` antigo)"""
    await _conta_ldap(sessoes, username="ana.antiga")
    for _ in range(5):
        assert (await _login(cliente, "ana", "senha-errada")).status_code == 401
    binds = diretorio.binds

    bloqueado = await _login(cliente, "ana")

    assert bloqueado.status_code == 401
    assert diretorio.binds == binds
    conta = await _conta(sessoes, ANA.external_id)
    assert conta is not None
    assert conta["locked_until"] is not None


async def _derivadas(sessoes: Sessoes, usuario: UUID) -> list[tuple[str, str]]:
    async with sessoes() as sessao:
        linhas = await sessao.execute(
            text(
                "SELECT r.code, a.origin FROM role_assignments a JOIN roles r ON r.id = a.role_id"
                " WHERE a.user_id = :id AND a.origin = 'group' ORDER BY r.code"
            ),
            {"id": usuario},
        )
        return [(str(codigo), str(origem)) for codigo, origem in linhas.all()]


async def test_login_recalcula_as_derivadas_pelos_grupos_do_diretorio(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes, diretorio: DiretorioFalso
) -> None:
    """004/R2.3, 003/R3.2 (revisão da frente A, S3: o grupo mapeado dá o papel no login; fora
    do grupo no diretório, o login seguinte tira o papel)"""
    async with sessoes() as sessao, sessao.begin():
        grupo = uuid7()
        await sessao.execute(
            text(
                "INSERT INTO groups (id, source, external_id, name)"
                " VALUES (:id, 'ldap', :ext, :nome)"
            ),
            {"id": grupo, "ext": TI.external_id, "nome": TI.name},
        )
    admin = bearer(app, await logado(sessoes, ("ADMIN_TI", GLOBAL)))
    mapeamento = await cliente.post(
        "/api/v1/admin/mapeamentos-grupo",
        json={"grupo_id": str(grupo), "papel": "AUDITOR", "escopo_tipo": "global"},
        headers=admin,
    )
    assert mapeamento.status_code == 201, mapeamento.text

    assert (await _login(cliente, ANA.login)).status_code == 200
    conta = await _conta(sessoes, ANA.external_id)
    assert conta is not None
    assert await _derivadas(sessoes, conta["id"]) == [("AUDITOR", "group")]
    assert len(await eventos(sessoes, "papel.atribuido")) == 1

    diretorio.grupos[ANA.dn] = ()
    assert (await _login(cliente, ANA.login)).status_code == 200

    assert await _derivadas(sessoes, conta["id"]) == []
    assert len(await eventos(sessoes, "papel.removido")) == 1


async def test_login_audita_a_mudanca_de_nome_e_email_sem_os_valores(
    cliente: httpx.AsyncClient, sessoes: Sessoes, diretorio: DiretorioFalso
) -> None:
    """004/R1.6, regra 5 do AGENTS.md (revisão da frente A, S4: `usuario.atualizado` só com os
    nomes dos campos; sem mudança, nada é gravado)"""
    conta = await _conta_ldap(sessoes)

    await _login(cliente, ANA.login)
    await _login(cliente, ANA.login)

    [atualizado] = await eventos(sessoes, "usuario.atualizado")
    assert atualizado["entity_id"] == str(conta)
    assert atualizado["metadata"] == {"origem": "ldap", "campos": ["display_name", "email"]}
    assert ANA.email is not None
    assert ANA.email not in str(atualizado)
    assert ANA.display_name not in str(atualizado)
