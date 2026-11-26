"""Login por OIDC (spec 004, T7; design § Fluxo, Login OIDC).

1. `iniciar_login_oidc` grava o pedido (hashes do `state` e do vínculo, `nonce`, `code_verifier`
   cifrado) e devolve a URL do provedor (R3.1, R3.8).
2. `consumir_pedido`, numa transação própria, confirmada antes de qualquer outro passo, marca o
   `state` como usado e confere o vínculo do cookie (R3.7): uma falha depois não reabre o `state`.
3. `concluir_login_oidc` troca o código, confere o `id_token` (no adaptador, R3.2, R3.6),
   provisiona a conta, espelha os grupos, recalcula as derivadas e abre a sessão (R3.3, R3.4,
   R4.3, R4.4).

Toda recusa volta como `RecusaOidc`, com um motivo da lista fechada do design e o `sub` quando
houver; a rota audita `auth.oidc_failed` e redireciona com o código genérico (R3.5). Nenhuma
escrita de provisionamento acontece antes de a recusa ser decidida.
"""

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final, Literal
from uuid import UUID

from src.modules.access.domain.ports import (
    RepositorioDeAtribuicoes,
    RepositorioDeMapeamentos,
    RepositorioDePermissoes,
)
from src.modules.identity.application.grupos import espelhar_grupos
from src.modules.identity.application.login import (
    Identidade,
    Origem,
    TokensEmitidos,
    abrir_sessao,
    auditar,
)
from src.modules.identity.domain.oidc import (
    MotivoDeRecusa,
    OidcIdentity,
    OidcLoginRequest,
    OidcPort,
    OidcRejected,
    code_challenge_s256,
    hash_do_valor,
    mesmo_valor,
)
from src.modules.identity.domain.ports import DirectoryRepository, OidcLoginRequestRepository
from src.modules.identity.domain.users import User, UserSource

VALIDADE_DO_PEDIDO: Final = timedelta(minutes=10)
GUARDA_DOS_VENCIDOS: Final = timedelta(days=1)  # apaga os vencidos há mais de um dia
AMR: Final = "oidc"  # o segundo fator é do provedor (ADR-0003; R3.6 para exigir)
GRUPOS_MAX: Final = 200
NOME_DE_GRUPO_MAX: Final = 255

type Motivo = (
    MotivoDeRecusa
    | Literal["state", "vinculo", "erro_do_provedor", "desativado", "conflito_de_conta"]
)


@dataclass(frozen=True)
class Oidc:
    """O que o login OIDC usa além da `Identidade`, preso à mesma sessão do banco.

    `porta` é None com o OIDC desligado (sem OIDC_ISSUER)."""

    porta: OidcPort | None
    pedidos: OidcLoginRequestRepository
    diretorio: DirectoryRepository
    mapeamentos: RepositorioDeMapeamentos
    atribuicoes: RepositorioDeAtribuicoes
    permissoes: RepositorioDePermissoes


@dataclass(frozen=True)
class InicioOidc:
    url: str
    vinculo: str  # valor do cookie `sgs_oidc`; só o hash fica no banco


@dataclass(frozen=True)
class RecusaOidc:
    motivo: Motivo
    sub: str | None = None
    usuario_id: UUID | None = None


async def iniciar_login_oidc(oidc: Oidc, porta: OidcPort, *, deps: Identidade) -> InicioOidc:
    """Design § Login OIDC, início, passos 1 a 3. `ServiceUnavailable` do adaptador sobe: o
    provedor fora do ar não deixa o pedido gravado (a transação é desfeita)."""
    agora = deps.relogio()
    state, nonce, vinculo = (secrets.token_urlsafe(32) for _ in range(3))
    code_verifier = secrets.token_urlsafe(48)  # 64 caracteres (RFC 7636 § 4.1)
    pedido_id = deps.gerar_id()
    await oidc.pedidos.delete_expired_before(agora - GUARDA_DOS_VENCIDOS)
    await oidc.pedidos.add(
        OidcLoginRequest(
            id=pedido_id,
            state_hash=hash_do_valor(state),
            binding_hash=hash_do_valor(vinculo),
            nonce=nonce,
            code_verifier_enc=deps.cifra.encrypt(code_verifier, aad=str(pedido_id)),
            created_at=agora,
            expires_at=agora + VALIDADE_DO_PEDIDO,
        )
    )
    url = await porta.authorization_url(
        state=state, nonce=nonce, code_challenge=code_challenge_s256(code_verifier)
    )
    return InicioOidc(url=url, vinculo=vinculo)


async def consumir_pedido(
    state: str | None, vinculo: str | None, *, pedidos: OidcLoginRequestRepository, agora: datetime
) -> OidcLoginRequest | RecusaOidc:
    """Callback, passo 1 (R3.7): uso único por `UPDATE ... WHERE used_at IS NULL`; o vínculo do
    cookie diferente recusa, e o `state` já fica usado."""
    if not state:
        return RecusaOidc("state")
    pedido = await pedidos.consume(hash_do_valor(state), agora)
    if pedido is None:
        return RecusaOidc("state")
    if not vinculo or not mesmo_valor(hash_do_valor(vinculo), pedido.binding_hash):
        return RecusaOidc("vinculo")
    return pedido


async def concluir_login_oidc(
    pedido: OidcLoginRequest,
    code: str | None,
    erro_do_provedor: str | None,
    *,
    oidc: Oidc,
    porta: OidcPort,
    origem: Origem,
    deps: Identidade,
) -> TokensEmitidos | RecusaOidc:
    """Callback, passos 2 a 4."""
    if erro_do_provedor is not None or not code:
        return RecusaOidc("erro_do_provedor")
    code_verifier = deps.cifra.decrypt(pedido.code_verifier_enc, aad=str(pedido.id))
    try:
        identidade = await porta.exchange(code, code_verifier=code_verifier, nonce=pedido.nonce)
    except OidcRejected as recusa:
        return RecusaOidc(recusa.motivo)
    if len(identidade.groups) > GRUPOS_MAX or any(
        not grupo or len(grupo) > NOME_DE_GRUPO_MAX for grupo in identidade.groups
    ):
        return RecusaOidc("claims", sub=identidade.sub)

    usuario = await _provisionar(identidade, oidc=oidc, origem=origem, deps=deps)
    if isinstance(usuario, RecusaOidc):
        return usuario
    await espelhar_grupos(
        usuario.id,
        "oidc",
        [(grupo, grupo) for grupo in identidade.groups],  # o `external_id` e o nome são o valor
        repositorio=oidc.diretorio,
        mapeamentos=oidc.mapeamentos,
        atribuicoes=oidc.atribuicoes,
        permissoes=oidc.permissoes,
        auditoria=deps.auditoria,
        origem=origem,
        gerar_id=deps.gerar_id,
        agora=deps.relogio(),
    )
    return await abrir_sessao(deps, usuario, AMR, origem)


async def _provisionar(
    dado: OidcIdentity, *, oidc: Oidc, origem: Origem, deps: Identidade
) -> User | RecusaOidc:
    """Passo 4: conta por (`oidc`, `sub`); cria, atualiza ou recusa (R3.3, R4.3, R4.4)."""
    agora = deps.relogio()
    conta = await deps.usuarios.get_by_external_id(UserSource.OIDC, dado.sub)
    if conta is not None and not conta.is_active:
        # R4.4: o login nunca reativa. Conferido antes, porque `update_synced_user` reativa
        # (revisão da frente A, N5).
        return RecusaOidc("desativado", sub=dado.sub, usuario_id=conta.id)
    if conta is None:
        if await _ocupado(deps, dado.username, dado.email):  # R4.3: nada é unido nem criado
            return RecusaOidc("conflito_de_conta", sub=dado.sub)
        nova = User(
            id=deps.gerar_id(),
            username=dado.username,
            display_name=dado.display_name,
            source=UserSource.OIDC,
            email=dado.email,
            external_id=dado.sub,
        )
        await oidc.diretorio.add_synced_user(nova, agora)
        await auditar(
            deps, "usuario.provisionado", origem, nova.id, {"origem": "oidc"}, tipo="sistema"
        )
        return nova
    # E-mail novo que já é de outra conta: fica o antigo, como no LDAP (R4.2).
    email = dado.email
    if email is not None and email != conta.email:
        dono = await deps.usuarios.get_by_email(email)
        if dono is not None and dono.id != conta.id:
            email = conta.email
    await oidc.diretorio.update_synced_user(
        conta.id, display_name=dado.display_name, email=email, agora=agora
    )
    return User(
        id=conta.id,
        username=conta.username,
        display_name=dado.display_name,
        source=UserSource.OIDC,
        email=email,
        external_id=conta.external_id,
    )


async def _ocupado(deps: Identidade, username: str, email: str | None) -> bool:
    if await deps.usuarios.get_by_username(username) is not None:
        return True
    return email is not None and await deps.usuarios.get_by_email(email) is not None
