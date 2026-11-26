"""`GET /me` e administração de atribuições (spec 003, R2 e R5; T6 e T7).

Toda atribuição ou remoção grava `papel.atribuido` ou `papel.removido` com quem concedeu (R2.4) e
incrementa `users.authz_version`, para a mudança valer na próxima requisição (R4.5).
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from src.core.errors import DomainValidationError, FieldError, NotFound
from src.modules.access.application.autorizacao import AcessoNegado, UsuarioAtual
from src.modules.access.domain.atribuicoes import Atribuicao, DadosDoUsuario, Papel
from src.modules.access.domain.authorization import Area, Distrito, Global, Unidade
from src.modules.access.domain.ports import RepositorioDeAtribuicoes, RepositorioDePermissoes
from src.modules.audit.application.registrar import Ator, AuditStore, Entidade, registrar

__all__ = [
    "Atribuicao",
    "Papel",
    "Perfil",
    "atribuir",
    "listar_atribuicoes",
    "listar_papeis",
    "perfil",
    "remover",
    "validar_escopo",
]

PERMISSAO = "papel:assign"


@dataclass(frozen=True, slots=True)
class Perfil:
    """R5.1: dados básicos, papéis com escopos e permissões efetivas."""

    usuario: DadosDoUsuario
    atribuicoes: tuple[Atribuicao, ...]
    permissoes: dict[str, list[dict[str, str | None]]]


def _escopo_em_texto(escopo: object) -> dict[str, str | None]:
    match escopo:
        case Global():
            return {"tipo": "global", "id": None}
        case Area(id=id_):
            return {"tipo": "area", "id": str(id_)}
        case Distrito(id=id_):
            return {"tipo": "distrito", "id": str(id_)}
        case Unidade(id=id_):
            return {"tipo": "unidade", "id": str(id_)}
    raise ValueError("escopo desconhecido")  # pragma: no cover


async def perfil(
    usuario: UsuarioAtual, *, atribuicoes: RepositorioDeAtribuicoes, agora: datetime
) -> Perfil:
    dados = await atribuicoes.usuario(usuario.id)
    if dados is None:  # pragma: no cover - o CurrentUser acabou de ler
        raise NotFound("Usuário não encontrado.")
    return Perfil(
        usuario=dados,
        atribuicoes=tuple(await atribuicoes.atribuicoes(usuario.id, agora)),
        permissoes={
            codigo: [_escopo_em_texto(e) for e in escopos]
            for codigo, escopos in sorted(usuario.permissoes.items())
        },
    )


async def listar_papeis(*, atribuicoes: RepositorioDeAtribuicoes) -> list[Papel]:
    return list(await atribuicoes.papeis())


async def listar_atribuicoes(
    usuario_id: UUID | None, *, atribuicoes: RepositorioDeAtribuicoes, agora: datetime
) -> list[Atribuicao]:
    return list(await atribuicoes.atribuicoes(usuario_id, agora))


async def atribuir(
    *,
    usuario_id: UUID,
    papel: str,
    escopo_tipo: str,
    escopo_id: str | None,
    valido_ate: datetime | None,
    quem: UsuarioAtual,
    ator: Ator,
    novo_id: UUID,
    atribuicoes: RepositorioDeAtribuicoes,
    permissoes: RepositorioDePermissoes,
    auditoria: AuditStore,
    relogio: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> Atribuicao:
    """R2.1 a R2.5: 403 para si mesmo; 422 para usuário, papel, escopo ou validade inválidos."""
    if usuario_id == quem.id:
        raise AcessoNegado(PERMISSAO)  # segregação de funções (R2.5)
    erros: list[FieldError] = []
    if await atribuicoes.usuario(usuario_id) is None:
        erros.append(FieldError(campo="usuario_id", mensagem="Usuário inexistente."))
    erros.extend(await validar_escopo(papel, escopo_tipo, escopo_id, atribuicoes=atribuicoes))
    if valido_ate is not None and valido_ate <= relogio():
        erros.append(FieldError(campo="valido_ate", mensagem="A validade precisa ser futura."))
    if erros:
        raise DomainValidationError("A requisição tem campos inválidos.", errors=erros)
    atribuicao = Atribuicao(
        id=novo_id,
        user_id=usuario_id,
        papel=papel,
        scope_type=escopo_tipo,
        scope_id=escopo_id,
        origin="direct",
        valid_until=valido_ate,
        granted_by=quem.id,
    )
    await atribuicoes.inserir(atribuicao)
    await permissoes.invalidar(usuario_id)
    await registrar(
        auditoria,
        acao="papel.atribuido",
        ator=ator,
        entidade=Entidade(tipo="usuario", id=str(usuario_id)),
        metadados={
            "atribuicao_id": str(atribuicao.id),
            "papel": papel,
            "escopo_tipo": escopo_tipo,
            "escopo_id": escopo_id,
            "valido_ate": None if valido_ate is None else valido_ate.isoformat(),
            "concedido_por": str(quem.id),
        },
    )
    return atribuicao


async def validar_escopo(
    papel: str, escopo_tipo: str, escopo_id: str | None, *, atribuicoes: RepositorioDeAtribuicoes
) -> list[FieldError]:
    """R2.1, R2.2: o papel existe, o escopo é o exigido por ele e existe. Vale também para o
    mapeamento de grupo (R3.1)."""
    erros: list[FieldError] = []
    definicao = await atribuicoes.papel(papel)
    if definicao is None:
        erros.append(FieldError(campo="papel", mensagem="Papel inexistente."))
    elif escopo_tipo != definicao.escopo_exigido:
        erros.append(
            FieldError(
                campo="escopo_tipo",
                mensagem=f"O papel {papel} exige escopo {definicao.escopo_exigido}.",
            )
        )
    if escopo_tipo == "global":
        if escopo_id is not None:
            erros.append(FieldError(campo="escopo_id", mensagem="Escopo global não tem id."))
    elif escopo_id is None or not await atribuicoes.escopo_existe(escopo_tipo, escopo_id):
        erros.append(FieldError(campo="escopo_id", mensagem="Escopo inexistente."))
    return erros


async def remover(
    id_: UUID,
    *,
    quem: UsuarioAtual,
    ator: Ator,
    atribuicoes: RepositorioDeAtribuicoes,
    permissoes: RepositorioDePermissoes,
    auditoria: AuditStore,
) -> None:
    """R2.4; segregação: ninguém remove as próprias atribuições (R2.5)."""
    atual = await atribuicoes.atribuicao(id_)
    if atual is None:
        raise NotFound("Atribuição não encontrada.")
    if atual.user_id == quem.id:
        raise AcessoNegado(PERMISSAO)
    await atribuicoes.remover(id_)
    await permissoes.invalidar(atual.user_id)
    await registrar(
        auditoria,
        acao="papel.removido",
        ator=ator,
        entidade=Entidade(tipo="usuario", id=str(atual.user_id)),
        metadados={
            "atribuicao_id": str(id_),
            "papel": atual.papel,
            "escopo_tipo": atual.scope_type,
            "escopo_id": atual.scope_id,
            "removido_por": str(quem.id),
        },
    )
