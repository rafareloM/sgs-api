"""Login local, segundo fator, refresh e logout (spec 002, R1 a R4; design § Rotas).

As falhas não levantam exceção: voltam como `Falha`, para a rota confirmar a transação (contador
de falhas, bloqueio, auditoria) antes de responder 401. Uma exceção desfaria tudo isso.

Mensagens de falha são sempre as mesmas (R1.3): não dizem se o usuário existe, se a senha errou,
se o usuário está bloqueado ou desativado.
"""

import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from src.modules.audit.application.registrar import Ator, AuditStore, Entidade, registrar
from src.modules.identity.domain.login import (
    MENSAGEM_DE_CREDENCIAIS,
    TENTATIVAS_DE_MFA,
    VALIDADE_DO_REFRESH,
    EstadoDeLogin,
)
from src.modules.identity.domain.passwords import PasswordHasher
from src.modules.identity.domain.ports import (
    LoginStateRepository,
    PapeisDoUsuario,
    RefreshTokenRepository,
    RefreshTokenWriter,
    SessionRepository,
    SessionRevoker,
    UserRepository,
)
from src.modules.identity.domain.sessions import AuthSession, RefreshToken, hash_refresh_token
from src.modules.identity.domain.tokens import InvalidTokenError, MfaPurpose, TokenService
from src.modules.identity.domain.totp import CifraDeCampo, VerificadorTotp
from src.modules.identity.domain.users import User, UserSource

__all__ = [
    "Falha",
    "Identidade",
    "Origem",
    "ResultadoDoLogin",
    "TokensEmitidos",
    "abrir_sessao",
    "auditar",
    "cadastrar_mfa",
    "confirmar_mfa",
    "desafiar_ou_abrir_sessao",
    "entrar",
    "renovar",
    "sair",
    "verificar_mfa",
]


ORIGEM_API = "api"
"""Rótulo de origem dos eventos de autenticação, gravados pelas rotas da API (013/R1.1)."""

_FALHAS_DE_AUTENTICACAO = frozenset({"auth.login_failed", "auth.mfa_failed", "auth.oidc_failed"})
"""013/R4.2: resultado `failure`, categoria `autenticacao`. Os demais eventos `auth.*` (login,
logout, 2FA cadastrado, bloqueio, reuso de refresh) registram uma ação que aconteceu: `success`."""


def _agora() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class Identidade:
    """As portas que o login usa, todas presas à mesma sessão do banco (uma transação)."""

    usuarios: UserRepository
    estados: LoginStateRepository
    sessoes: SessionRepository
    refresh: RefreshTokenRepository
    refresh_escrita: RefreshTokenWriter
    revogacao: SessionRevoker
    auditoria: AuditStore
    tokens: TokenService
    hasher: PasswordHasher
    totp: VerificadorTotp
    cifra: CifraDeCampo
    gerar_id: Callable[[], UUID]
    """UUID v7 (`src.core.ids.uuid7`, que a application não importa; ver o import-linter)."""
    mfa_obrigatorio: bool = True
    relogio: Callable[[], datetime] = field(default=_agora)
    papeis: PapeisDoUsuario | None = None
    """Papéis efetivos para o `auth.login` (013/R1.4); sem a porta, o evento sai sem papéis."""


@dataclass(frozen=True)
class Origem:
    """De onde veio a requisição, para a sessão e a auditoria (R4.1)."""

    ip: str | None
    user_agent: str | None
    request_id: str | None = None


@dataclass(frozen=True)
class Falha:
    """401 (ou 403 no anti-CSRF). `mensagem` vai para o cliente; o resto já foi auditado."""

    mensagem: str = MENSAGEM_DE_CREDENCIAIS
    status: int = 401


@dataclass(frozen=True)
class TokensEmitidos:
    access_token: str = field(repr=False)
    expires_in: int
    refresh_token: str = field(repr=False)
    refresh_expira_em: datetime


@dataclass(frozen=True)
class ResultadoDoLogin:
    """Login com senha certa: ou o desafio do 2FA, ou (2FA desligado em dev) os tokens."""

    mfa_required: bool = False
    mfa_enrollment_required: bool = False
    mfa_token: str | None = field(default=None, repr=False)
    tokens: TokensEmitidos | None = None


# ----------------------------------------------------------------------- login


async def entrar(
    username: str, senha: str, *, origem: Origem, deps: Identidade
) -> ResultadoDoLogin | Falha:
    """R1.1 a R1.7: senha conferida com tempo semelhante para usuário inexistente; 5 falhas
    seguidas bloqueiam por 15 min; desativado é recusado; com 2FA, devolve o `mfa_token`."""
    agora = deps.relogio()
    usuario = await deps.usuarios.get_by_username(username)
    if usuario is None or usuario.source is not UserSource.LOCAL or usuario.password_hash is None:
        deps.hasher.verificar_ficticio(senha)
        await auditar(deps, "auth.login_failed", origem, None, {"motivo": "credenciais"})
        return Falha()
    estado = await deps.estados.estado(usuario.id)
    if estado is None:  # pragma: no cover - acabou de ser lido
        return Falha()
    if estado.bloqueado(agora):
        deps.hasher.verificar_ficticio(senha)
        await auditar(deps, "auth.login_failed", origem, usuario.id, {"motivo": "bloqueado"})
        return Falha()
    if not deps.hasher.verificar(senha, usuario.password_hash):
        depois = await deps.estados.registrar_falha(usuario.id, agora)
        await auditar(deps, "auth.login_failed", origem, usuario.id, {"motivo": "credenciais"})
        if depois.bloqueado(agora):
            await auditar(deps, "auth.locked", origem, usuario.id, {}, tipo="sistema")
        return Falha()
    if not usuario.is_active:
        await auditar(deps, "auth.login_failed", origem, usuario.id, {"motivo": "desativado"})
        return Falha()

    await deps.estados.registrar_sucesso(usuario.id, agora)
    return await desafiar_ou_abrir_sessao(usuario, estado, origem=origem, deps=deps)


async def desafiar_ou_abrir_sessao(
    usuario: User, estado: EstadoDeLogin, *, origem: Origem, deps: Identidade
) -> ResultadoDoLogin:
    """Depois da senha conferida (local ou no diretório): o desafio do 2FA (R1.1, R1.2) ou, com
    o 2FA desligado em dev, a sessão."""
    if not deps.mfa_obrigatorio:  # só em dev (Settings recusa fora dele)
        tokens = await abrir_sessao(deps, usuario, _amr(usuario, otp=False), origem)
        return ResultadoDoLogin(tokens=tokens)
    finalidade = MfaPurpose.VERIFY if estado.mfa_enabled else MfaPurpose.ENROLL
    emitido = deps.tokens.issue_mfa_token(usuario.id, finalidade)
    await deps.estados.novo_desafio(usuario.id, emitido.jti)
    return ResultadoDoLogin(
        mfa_required=finalidade is MfaPurpose.VERIFY,
        mfa_enrollment_required=finalidade is MfaPurpose.ENROLL,
        mfa_token=emitido.token,
    )


# --------------------------------------------------------------- segundo fator


async def cadastrar_mfa(mfa_token: str, *, deps: Identidade) -> str | Falha:
    """R2.1: gera o segredo, guarda cifrado (R2.5) e devolve a URI `otpauth://` uma vez.

    Chamar de novo antes de confirmar troca o segredo (o anterior nunca foi ativado).
    """
    usuario = await _dono_do_desafio(mfa_token, MfaPurpose.ENROLL, deps)
    if isinstance(usuario, Falha):
        return usuario
    segredo = deps.totp.novo_segredo()
    await deps.estados.gravar_segredo(usuario.id, deps.cifra.encrypt(segredo, aad=str(usuario.id)))
    return deps.totp.uri(segredo, usuario.username)


async def confirmar_mfa(
    mfa_token: str, codigo: str, *, origem: Origem, deps: Identidade
) -> TokensEmitidos | Falha:
    """R2.2: código válido ativa o 2FA e emite os tokens; audita `auth.mfa_enrolled`."""
    return await _concluir_mfa(mfa_token, codigo, MfaPurpose.ENROLL, origem, deps)


async def verificar_mfa(
    mfa_token: str, codigo: str, *, origem: Origem, deps: Identidade
) -> TokensEmitidos | Falha:
    """R2.3, R2.4, R2.6: código válido, não reusado, no desafio vigente, emite os tokens."""
    return await _concluir_mfa(mfa_token, codigo, MfaPurpose.VERIFY, origem, deps)


async def _concluir_mfa(
    mfa_token: str, codigo: str, finalidade: MfaPurpose, origem: Origem, deps: Identidade
) -> TokensEmitidos | Falha:
    usuario = await _dono_do_desafio(mfa_token, finalidade, deps)
    if isinstance(usuario, Falha):
        return usuario
    estado = await deps.estados.estado(usuario.id)
    if estado is None or estado.mfa_secret_enc is None:
        return Falha("Código inválido.")
    segredo = deps.cifra.decrypt(estado.mfa_secret_enc, aad=str(usuario.id))
    passo = deps.totp.passo_valido(segredo, codigo, deps.relogio())
    reuso = passo is not None and estado.mfa_last_step is not None and passo <= estado.mfa_last_step
    if passo is None or reuso:
        tentativas = await deps.estados.falha_de_mfa(usuario.id)
        await auditar(
            deps,
            "auth.mfa_failed",
            origem,
            usuario.id,
            {
                "tentativas": tentativas,
                "reuso": reuso,
                "desafio_invalidado": tentativas >= TENTATIVAS_DE_MFA,
            },
        )
        return Falha("Código inválido.")
    ativar = finalidade is MfaPurpose.ENROLL
    await deps.estados.concluir_mfa(usuario.id, passo, ativar=ativar)
    if ativar:
        await auditar(deps, "auth.mfa_enrolled", origem, usuario.id, {})
    return await abrir_sessao(deps, usuario, _amr(usuario, otp=True), origem)


def _amr(usuario: User, *, otp: bool) -> str:
    """Como a senha foi conferida: `ldap` no diretório (004, D004-16), `pwd` na senha local."""
    base = "ldap" if usuario.source is UserSource.LDAP else "pwd"
    return f"{base}+otp" if otp else base


async def _dono_do_desafio(
    mfa_token: str, finalidade: MfaPurpose, deps: Identidade
) -> User | Falha:
    """O usuário do `mfa_token`, se ele é o desafio vigente (o `jti` gravado, R2.6)."""
    try:
        claims = deps.tokens.verify_mfa_token(mfa_token, finalidade)
    except InvalidTokenError:
        return Falha("Token inválido ou expirado.")
    usuario = await deps.usuarios.get_by_id(claims.user_id)
    estado = None if usuario is None else await deps.estados.estado(usuario.id)
    if usuario is None or estado is None or not usuario.is_active:
        return Falha("Token inválido ou expirado.")
    if estado.mfa_challenge_jti != claims.jti:
        return Falha("Token inválido ou expirado.")
    return usuario


# ---------------------------------------------------------- refresh e logout


async def renovar(
    refresh_token: str, *, origem: Origem, deps: Identidade
) -> TokensEmitidos | Falha:
    """R3.4, R3.5: refresh válido vira um par novo (rotação); um já usado revoga a sessão
    inteira e audita `auth.refresh_reuse`."""
    agora = deps.relogio()
    registro = await deps.refresh.get_by_hash(hash_refresh_token(refresh_token))
    if registro is None:
        return Falha("Sessão expirada.")
    sessao = await deps.sessoes.get_by_id(registro.session_id)
    if sessao is None:  # pragma: no cover - FK
        return Falha("Sessão expirada.")
    if registro.used_at is not None or not await deps.refresh_escrita.marcar_usado(
        registro.id, agora
    ):
        await deps.revogacao.revogar(sessao.id, agora)
        await auditar(deps, "auth.refresh_reuse", origem, sessao.user_id, {}, sessao_id=sessao.id)
        return Falha("Sessão expirada.")
    usuario = await deps.usuarios.get_by_id(sessao.user_id)
    if (
        sessao.revoked_at is not None
        or registro.revoked_at is not None
        or registro.expires_at <= agora
        or usuario is None
        or not usuario.is_active
    ):
        return Falha("Sessão expirada.")
    return await _emitir(deps, sessao, registro.family_id, agora)


async def sair(usuario_id: UUID, sessao_id: UUID, *, origem: Origem, deps: Identidade) -> None:
    """R3.7: revoga a sessão e os refresh dela; audita `auth.logout`."""
    await deps.revogacao.revogar(sessao_id, deps.relogio())
    await auditar(deps, "auth.logout", origem, usuario_id, {}, sessao_id=sessao_id)


# ------------------------------------------------------------------- auxiliares


async def abrir_sessao(deps: Identidade, usuario: User, amr: str, origem: Origem) -> TokensEmitidos:
    agora = deps.relogio()
    sessao = AuthSession(
        id=deps.gerar_id(),
        user_id=usuario.id,
        amr=amr,
        created_at=agora,
        ip=origem.ip,
        user_agent=origem.user_agent,
    )
    await deps.sessoes.add(sessao)
    tokens = await _emitir(deps, sessao, deps.gerar_id(), agora)
    papeis = await deps.papeis.de(usuario.id) if deps.papeis is not None else ()
    await auditar(
        deps,
        "auth.login",
        origem,
        usuario.id,
        {"amr": amr},
        sessao_id=sessao.id,
        papeis=papeis,
    )
    return tokens


async def _emitir(
    deps: Identidade, sessao: AuthSession, familia: UUID, agora: datetime
) -> TokensEmitidos:
    claro = secrets.token_urlsafe(32)
    expira = agora + VALIDADE_DO_REFRESH
    await deps.refresh.add(
        RefreshToken(
            id=deps.gerar_id(),
            session_id=sessao.id,
            family_id=familia,
            token_hash=hash_refresh_token(claro),
            expires_at=expira,
        )
    )
    acesso = deps.tokens.issue_access_token(sessao)
    return TokensEmitidos(
        access_token=acesso.token,
        expires_in=acesso.expires_in,
        refresh_token=claro,
        refresh_expira_em=expira,
    )


async def auditar(
    deps: Identidade,
    acao: str,
    origem: Origem,
    usuario_id: UUID | None,
    detalhes: Mapping[str, Any],
    *,
    sessao_id: UUID | None = None,
    papeis: tuple[str, ...] = (),
    tipo: str | None = None,
) -> None:
    """R4.1: evento de acesso com IP e user agent (nunca senha nem token).

    013/R1.1 a R1.3: sem usuário identificado, o ator é `anonimo`; um ato do próprio sistema
    (`auth.locked`) é `sistema`, sem usuário no ator e com a conta na entidade; o resto é o
    `usuario` da conta. O tipo é decidido aqui, nunca pelo que o cliente envia."""
    tipo = tipo or ("anonimo" if usuario_id is None else "usuario")
    falhou = acao in _FALHAS_DE_AUTENTICACAO
    await registrar(
        deps.auditoria,
        acao=acao,
        ator=Ator(
            tipo=tipo,
            origem=ORIGEM_API,
            user_id=usuario_id if tipo == "usuario" else None,
            papeis=papeis,
            session_id=sessao_id,
            ip=origem.ip,
            user_agent=origem.user_agent,
            request_id=origem.request_id,
        ),
        entidade=None if usuario_id is None else Entidade(tipo="usuario", id=str(usuario_id)),
        # 013/R3.4: o User-Agent vai na coluna (antes da 013 ia em `metadata.user_agent`).
        metadados=detalhes,
        resultado="failure" if falhou else "success",
        categoria="autenticacao" if falhou else None,
    )
