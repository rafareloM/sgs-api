"""Mapeamentos grupo→papel e atribuições derivadas (spec 003, R3; design § Rotas,
`/admin/mapeamentos-grupo`).

Os casos de uso rodam na transação de quem chama: o mapeamento, as atribuições derivadas, o
incremento de `users.authz_version` de cada usuário afetado (R4.5) e a auditoria são gravados
juntos ou nenhum. As atribuições diretas nunca são tocadas (R3.3).
"""

from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from uuid import UUID

from src.core.errors import Conflict, DomainValidationError, FieldError, NotFound
from src.modules.access.application.atribuicoes import (
    PERMISSAO,
    campos_de_auditoria,
    escopo_valido,
)
from src.modules.access.application.autorizacao import AcessoNegado, Recurso, UsuarioAtual
from src.modules.access.domain.atribuicoes import Atribuicao, colunas_do_escopo
from src.modules.access.domain.mapeamentos import MapeamentoDeGrupo, recalcular
from src.modules.access.domain.ports import (
    MembrosDeGrupo,
    RepositorioDeAtribuicoes,
    RepositorioDeMapeamentos,
    RepositorioDePermissoes,
)
from src.modules.audit.application.registrar import (
    Ator,
    AuditStore,
    Entidade,
    Mudanca,
    registrar,
)

__all__ = [
    "PERMISSAO",
    "MapeamentoDeGrupo",
    "PaginaDeMapeamentos",
    "PedidoDeMapeamento",
    "criar_mapeamento",
    "listar_mapeamentos",
    "recalcular_derivadas_do_usuario",
    "remover_mapeamento",
]

# `entity_type` dos eventos `mapeamento.criado` e `mapeamento.removido`.
ENTIDADE = "mapeamento_grupo"
# `entity_type` dos eventos `papel.atribuido` e `papel.removido` (o mesmo da 003/T7).
ENTIDADE_ATRIBUICAO = "atribuicao"


@dataclass(frozen=True)
class PedidoDeMapeamento:
    """O que a rota recebe: o escopo vem como nível e id em texto (nulo se global)."""

    grupo_id: UUID
    papel: str
    nivel: str
    id_do_escopo: str | None


@dataclass(frozen=True)
class PaginaDeMapeamentos:
    itens: Sequence[MapeamentoDeGrupo]
    total: int


async def criar_mapeamento(
    pedido: PedidoDeMapeamento,
    *,
    novo_id: UUID,
    usuario: UsuarioAtual,
    ator: Ator,
    mapeamentos: RepositorioDeMapeamentos,
    atribuicoes: RepositorioDeAtribuicoes,
    membros: MembrosDeGrupo,
    permissoes: RepositorioDePermissoes,
    auditoria: AuditStore,
    gerar_id: Callable[[], UUID],
) -> MapeamentoDeGrupo:
    """Mapeia o grupo para o papel no escopo e atribui o papel a cada membro ativo (R3.1).

    O escopo segue as regras da atribuição (R2.1, R2.2): `DomainValidationError` (422) se o papel
    não existe, se o nível não é o dele ou se o escopo não existe. `Conflict` (409) se o mesmo
    mapeamento já existe. `AcessoNegado` (403) se quem mapeia é membro do grupo: ele atribuiria
    papel a si mesmo (R2.5).
    """
    erros: list[FieldError] = []
    escopo = await escopo_valido(
        pedido.papel, pedido.nivel, pedido.id_do_escopo, atribuicoes=atribuicoes, erros=erros
    )
    if escopo is None or erros:
        raise DomainValidationError("A requisição tem campos inválidos.", errors=erros)
    if await mapeamentos.ha_mapeamento(pedido.grupo_id, pedido.papel, escopo):
        raise Conflict("O grupo já está mapeado para este papel neste escopo.")
    membros_ativos = await membros.membros_ativos(pedido.grupo_id)
    if usuario.id in membros_ativos:
        raise AcessoNegado(
            PERMISSAO,
            Recurso(tipo="grupo", id=str(pedido.grupo_id)),
            extensoes={
                "motivo": "Ninguém mapeia um grupo de que é membro: seria atribuir papel a si "
                "mesmo (segregação de funções)."
            },
        )
    mapeamento = MapeamentoDeGrupo(
        id=novo_id,
        grupo_id=pedido.grupo_id,
        papel=pedido.papel,
        escopo=escopo,
        criado_por=usuario.id,
    )
    await mapeamentos.inserir(mapeamento)
    await registrar(
        auditoria,
        acao="mapeamento.criado",
        ator=ator,
        entidade=Entidade(tipo=ENTIDADE, id=str(mapeamento.id)),
        mudancas=[Mudanca(campo=c, de=None, para=v) for c, v in _campos(mapeamento).items()],
    )
    for membro in sorted(membros_ativos):
        await _criar_derivada(
            membro,
            mapeamento,
            novo_id=gerar_id(),
            ator=ator,
            atribuicoes=atribuicoes,
            permissoes=permissoes,
            auditoria=auditoria,
        )
    return mapeamento


async def remover_mapeamento(
    mapeamento_id: UUID,
    *,
    ator: Ator,
    mapeamentos: RepositorioDeMapeamentos,
    atribuicoes: RepositorioDeAtribuicoes,
    permissoes: RepositorioDePermissoes,
    auditoria: AuditStore,
) -> None:
    """Remove o mapeamento e as atribuições derivadas dele (R3.2); as diretas ficam (R3.3).

    Levanta `NotFound` (404) se ele não existe.
    """
    mapeamento = await mapeamentos.obter(mapeamento_id)
    if mapeamento is None:
        raise NotFound("O mapeamento pedido não existe.")
    for derivada in await mapeamentos.derivadas_do_mapeamento(mapeamento_id):
        await _remover_derivada(
            derivada, ator=ator, atribuicoes=atribuicoes, permissoes=permissoes, auditoria=auditoria
        )
    await mapeamentos.remover(mapeamento_id)
    await registrar(
        auditoria,
        acao="mapeamento.removido",
        ator=ator,
        entidade=Entidade(tipo=ENTIDADE, id=str(mapeamento.id)),
        mudancas=[Mudanca(campo=c, de=v, para=None) for c, v in _campos(mapeamento).items()],
    )


async def listar_mapeamentos(
    *, pagina: int, tamanho: int, mapeamentos: RepositorioDeMapeamentos
) -> PaginaDeMapeamentos:
    itens, total = await mapeamentos.listar(deslocamento=(pagina - 1) * tamanho, limite=tamanho)
    return PaginaDeMapeamentos(itens=itens, total=total)


async def recalcular_derivadas_do_usuario(
    usuario_id: UUID,
    grupos: Collection[UUID],
    *,
    ator: Ator,
    mapeamentos: RepositorioDeMapeamentos,
    atribuicoes: RepositorioDeAtribuicoes,
    permissoes: RepositorioDePermissoes,
    auditoria: AuditStore,
    gerar_id: Callable[[], UUID],
) -> None:
    """Acerta as atribuições derivadas do usuário aos grupos em que ele está agora (R3.2).

    Quem espelha os grupos do diretório (spec 004: sincronização LDAP, login, callback OIDC)
    chama na mesma transação, com todos os grupos atuais do usuário. Cria a atribuição de cada
    mapeamento dos grupos que ele ainda não tem, remove a dos grupos que ele deixou e não toca
    nas diretas (R3.3). Sem mudança, não grava nada nem invalida o cache.
    """
    recalculo = recalcular(
        await mapeamentos.dos_grupos(grupos), await mapeamentos.derivadas_do_usuario(usuario_id)
    )
    for derivada in recalculo.remover:
        await _remover_derivada(
            derivada, ator=ator, atribuicoes=atribuicoes, permissoes=permissoes, auditoria=auditoria
        )
    for mapeamento in recalculo.criar:
        await _criar_derivada(
            usuario_id,
            mapeamento,
            novo_id=gerar_id(),
            ator=ator,
            atribuicoes=atribuicoes,
            permissoes=permissoes,
            auditoria=auditoria,
        )


async def _criar_derivada(
    usuario_id: UUID,
    mapeamento: MapeamentoDeGrupo,
    *,
    novo_id: UUID,
    ator: Ator,
    atribuicoes: RepositorioDeAtribuicoes,
    permissoes: RepositorioDePermissoes,
    auditoria: AuditStore,
) -> None:
    derivada = Atribuicao(
        id=novo_id,
        usuario_id=usuario_id,
        papel=mapeamento.papel,
        escopo=mapeamento.escopo,
        origem="group",
        mapeamento_id=mapeamento.id,
    )
    await atribuicoes.inserir(derivada)
    await permissoes.invalidar(usuario_id)
    await registrar(
        auditoria,
        acao="papel.atribuido",
        ator=ator,
        entidade=Entidade(tipo=ENTIDADE_ATRIBUICAO, id=str(derivada.id)),
        mudancas=[
            Mudanca(campo=c, de=None, para=v) for c, v in campos_de_auditoria(derivada).items()
        ],
    )


async def _remover_derivada(
    derivada: Atribuicao,
    *,
    ator: Ator,
    atribuicoes: RepositorioDeAtribuicoes,
    permissoes: RepositorioDePermissoes,
    auditoria: AuditStore,
) -> None:
    await atribuicoes.remover(derivada.id)
    await permissoes.invalidar(derivada.usuario_id)
    await registrar(
        auditoria,
        acao="papel.removido",
        ator=ator,
        entidade=Entidade(tipo=ENTIDADE_ATRIBUICAO, id=str(derivada.id)),
        mudancas=[
            Mudanca(campo=c, de=v, para=None) for c, v in campos_de_auditoria(derivada).items()
        ],
    )


def _campos(mapeamento: MapeamentoDeGrupo) -> dict[str, str | None]:
    """Os campos do mapeamento na auditoria, como valores JSON."""
    nivel, id_do_escopo = colunas_do_escopo(mapeamento.escopo)
    return {
        "grupo_id": str(mapeamento.grupo_id),
        "papel": mapeamento.papel,
        "escopo_tipo": nivel,
        "escopo_id": id_do_escopo,
    }
