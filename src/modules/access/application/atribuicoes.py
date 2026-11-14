"""Administração de atribuições de papel (spec 003, R2; design § Rotas, `/admin/atribuicoes`).

Os casos de uso que alteram rodam na transação da requisição: a atribuição, o incremento de
`users.authz_version` (R4.5) e o registro de auditoria (R2.4) são gravados juntos ou nenhum.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from src.core.errors import Conflict, DomainValidationError, FieldError, NotFound
from src.modules.access.application.autorizacao import AcessoNegado, Recurso, UsuarioAtual
from src.modules.access.domain.atribuicoes import Atribuicao, colunas_do_escopo, niveis_aceitos
from src.modules.access.domain.authorization import Escopo, escopo_de
from src.modules.access.domain.ports import RepositorioDeAtribuicoes, RepositorioDePermissoes
from src.modules.audit.application.registrar import (
    Ator,
    AuditStore,
    Entidade,
    Mudanca,
    registrar,
)
from src.modules.identity.application.autenticacao import UserRepository

__all__ = [
    "PERMISSAO",
    "Atribuicao",
    "PaginaDeAtribuicoes",
    "PedidoDeAtribuicao",
    "atribuir_papel",
    "campos_de_auditoria",
    "escopo_valido",
    "listar_atribuicoes",
    "remover_atribuicao",
]

# Permissão das rotas de atribuição (design § Rotas).
PERMISSAO = "papel:assign"

# `entity_type` dos eventos `papel.atribuido` e `papel.removido`.
ENTIDADE = "atribuicao"


@dataclass(frozen=True)
class PedidoDeAtribuicao:
    """O que a rota recebe: o escopo vem como nível e id em texto (nulo se global)."""

    usuario_id: UUID
    papel: str
    nivel: str
    id_do_escopo: str | None
    valido_ate: datetime | None = None


@dataclass(frozen=True)
class PaginaDeAtribuicoes:
    itens: Sequence[Atribuicao]
    total: int


def _agora() -> datetime:
    return datetime.now(UTC)


async def atribuir_papel(
    pedido: PedidoDeAtribuicao,
    *,
    novo_id: UUID,
    usuario: UsuarioAtual,
    ator: Ator,
    atribuicoes: RepositorioDeAtribuicoes,
    usuarios: UserRepository,
    permissoes: RepositorioDePermissoes,
    auditoria: AuditStore,
    agora: datetime | None = None,
) -> Atribuicao:
    """Atribui o papel ao usuário no escopo pedido (R2.1) e registra `papel.atribuido` (R2.4).

    Levanta `AcessoNegado` (403) se o usuário atribui a si mesmo (R2.5), `DomainValidationError`
    (422) se o usuário ou o papel não existe, se a expiração já passou (R2.3), se o nível do
    escopo não é o do papel ou se o escopo não existe (R2.2), e `Conflict` (409) se a mesma
    atribuição direta já está vigente.
    """
    agora = agora or _agora()
    if pedido.usuario_id == usuario.id:
        raise AcessoNegado(
            PERMISSAO,
            Recurso(tipo="usuario", id=str(pedido.usuario_id)),
            extensoes={"motivo": "Ninguém atribui papel a si mesmo (segregação de funções)."},
        )
    erros: list[FieldError] = []
    if await usuarios.get_by_id(pedido.usuario_id) is None:
        erros.append(FieldError(campo="usuario_id", mensagem="Usuário não encontrado."))
    if pedido.valido_ate is not None and pedido.valido_ate <= agora:
        erros.append(FieldError(campo="valido_ate", mensagem="A expiração precisa ser futura."))
    escopo = await escopo_valido(
        pedido.papel, pedido.nivel, pedido.id_do_escopo, atribuicoes=atribuicoes, erros=erros
    )
    if escopo is None or erros:
        raise DomainValidationError("A requisição tem campos inválidos.", errors=erros)
    if await atribuicoes.ha_direta_vigente(pedido.usuario_id, pedido.papel, escopo, agora):
        raise Conflict("O usuário já tem este papel neste escopo.")
    atribuicao = Atribuicao(
        id=novo_id,
        usuario_id=pedido.usuario_id,
        papel=pedido.papel,
        escopo=escopo,
        origem="direct",
        concedida_por=usuario.id,
        valido_ate=pedido.valido_ate,
    )
    await atribuicoes.inserir(atribuicao)
    await permissoes.invalidar(pedido.usuario_id)
    await registrar(
        auditoria,
        acao="papel.atribuido",
        ator=ator,
        entidade=Entidade(tipo=ENTIDADE, id=str(atribuicao.id)),
        mudancas=[
            Mudanca(campo=c, de=None, para=v) for c, v in campos_de_auditoria(atribuicao).items()
        ],
    )
    return atribuicao


async def escopo_valido(
    papel: str,
    nivel: str,
    id_do_escopo: str | None,
    *,
    atribuicoes: RepositorioDeAtribuicoes,
    erros: list[FieldError],
) -> Escopo | None:
    """O escopo pedido, se o papel existe, o nível é o dele e o escopo existe (R2.1, R2.2);
    senão anota o erro. Vale também para o mapeamento de grupo (R3.1)."""
    maximos = await atribuicoes.escopos_maximos(papel)
    if maximos is None:
        erros.append(FieldError(campo="papel", mensagem="Papel não encontrado."))
        return None
    aceitos = niveis_aceitos(maximos)
    if nivel not in aceitos:
        exigido = " ou ".join(sorted(aceitos))
        erros.append(
            FieldError(campo="escopo.tipo", mensagem=f"O papel {papel} exige escopo {exigido}.")
        )
        return None
    try:
        escopo = escopo_de(nivel, id_do_escopo)
    except ValueError:
        escopo = None
    if escopo is None or not await atribuicoes.escopo_existe(escopo):
        erros.append(FieldError(campo="escopo.id", mensagem="Escopo não encontrado."))
        return None
    return escopo


async def remover_atribuicao(
    atribuicao_id: UUID,
    *,
    ator: Ator,
    atribuicoes: RepositorioDeAtribuicoes,
    permissoes: RepositorioDePermissoes,
    auditoria: AuditStore,
) -> None:
    """Remove a atribuição direta e registra `papel.removido` com o que ela era (R2.4).

    Levanta `NotFound` (404) se ela não existe e `Conflict` (409) se é derivada de grupo: essa só
    sai pelo mapeamento ou pela saída do grupo (R3.2, R3.3).
    """
    atribuicao = await atribuicoes.obter(atribuicao_id)
    if atribuicao is None:
        raise NotFound("A atribuição pedida não existe.")
    if atribuicao.origem != "direct":
        raise Conflict("A atribuição vem de um grupo do diretório; altere o mapeamento do grupo.")
    await atribuicoes.remover(atribuicao_id)
    await permissoes.invalidar(atribuicao.usuario_id)
    await registrar(
        auditoria,
        acao="papel.removido",
        ator=ator,
        entidade=Entidade(tipo=ENTIDADE, id=str(atribuicao.id)),
        mudancas=[
            Mudanca(campo=c, de=v, para=None) for c, v in campos_de_auditoria(atribuicao).items()
        ],
    )


async def listar_atribuicoes(
    usuario_id: UUID | None,
    *,
    pagina: int,
    tamanho: int,
    atribuicoes: RepositorioDeAtribuicoes,
    agora: datetime | None = None,
) -> PaginaDeAtribuicoes:
    """Uma página das atribuições vigentes, de um usuário ou de todos; as expiradas ficam de fora
    (R2.3)."""
    itens, total = await atribuicoes.listar(
        usuario_id, agora or _agora(), deslocamento=(pagina - 1) * tamanho, limite=tamanho
    )
    return PaginaDeAtribuicoes(itens=itens, total=total)


def campos_de_auditoria(atribuicao: Atribuicao) -> dict[str, str | None]:
    """Os campos da atribuição na auditoria, como valores JSON; a derivada de grupo leva também
    o `mapeamento_id` (R3)."""
    nivel, id_do_escopo = colunas_do_escopo(atribuicao.escopo)
    campos = {
        "usuario_id": str(atribuicao.usuario_id),
        "papel": atribuicao.papel,
        "escopo_tipo": nivel,
        "escopo_id": id_do_escopo,
        "valido_ate": None if atribuicao.valido_ate is None else atribuicao.valido_ate.isoformat(),
    }
    if atribuicao.mapeamento_id is not None:
        campos["mapeamento_id"] = str(atribuicao.mapeamento_id)
    return campos
