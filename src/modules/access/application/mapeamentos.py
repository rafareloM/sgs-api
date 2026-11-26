"""Mapeamentos grupo→papel e atribuições derivadas (spec 003, R3; T8).

Os casos de uso rodam na transação de quem chama: o mapeamento, as atribuições derivadas, o
incremento de `users.authz_version` de cada usuário afetado (R4.5) e a auditoria são gravados
juntos ou nenhum. Cada derivada criada ou removida grava `papel.atribuido` ou `papel.removido`,
como a atribuição direta (R2.4), com o `mapeamento_id` a mais. As atribuições diretas nunca são
tocadas (R3.3).
"""

from collections.abc import Callable, Collection
from uuid import UUID

from src.core.errors import Conflict, DomainValidationError, FieldError, NotFound
from src.modules.access.application.atribuicoes import PERMISSAO, validar_escopo
from src.modules.access.application.autorizacao import AcessoNegado, Recurso, UsuarioAtual
from src.modules.access.domain.atribuicoes import Atribuicao
from src.modules.access.domain.mapeamentos import MapeamentoDeGrupo, recalcular
from src.modules.access.domain.ports import (
    MembrosDeGrupo,
    RepositorioDeAtribuicoes,
    RepositorioDeMapeamentos,
    RepositorioDePermissoes,
)
from src.modules.audit.application.registrar import Ator, AuditStore, Entidade, registrar

__all__ = [
    "PERMISSAO",
    "MapeamentoDeGrupo",
    "criar_mapeamento",
    "listar_mapeamentos",
    "recalcular_derivadas_do_usuario",
    "remover_mapeamento",
]

# `entity_type` dos eventos `mapeamento.criado` e `mapeamento.removido`.
ENTIDADE = "mapeamento_grupo"


async def criar_mapeamento(
    *,
    grupo_id: UUID,
    papel: str,
    escopo_tipo: str,
    escopo_id: str | None,
    quem: UsuarioAtual,
    ator: Ator,
    novo_id: UUID,
    mapeamentos: RepositorioDeMapeamentos,
    atribuicoes: RepositorioDeAtribuicoes,
    membros: MembrosDeGrupo,
    permissoes: RepositorioDePermissoes,
    auditoria: AuditStore,
    gerar_id: Callable[[], UUID],
) -> MapeamentoDeGrupo:
    """Mapeia o grupo para o papel no escopo e atribui o papel a cada membro ativo (R3.1).

    O escopo segue as regras da atribuição (R2.1, R2.2): `DomainValidationError` (422) se o grupo
    ou o papel não existe, se o escopo não é o exigido por ele ou se não existe. `Conflict` (409)
    se o mesmo mapeamento já existe. `AcessoNegado` (403) se quem mapeia é membro do grupo: ele
    atribuiria papel a si mesmo (R2.5).
    """
    erros = await validar_escopo(papel, escopo_tipo, escopo_id, atribuicoes=atribuicoes)
    if not await mapeamentos.grupo_existe(grupo_id):
        # Revisão da frente A, S2: sem isto, a FK recusava e a resposta era 500.
        erros = [*erros, FieldError(campo="grupo_id", mensagem="Grupo inexistente.")]
    if erros:
        raise DomainValidationError("A requisição tem campos inválidos.", errors=erros)
    if await mapeamentos.ha_mapeamento(grupo_id, papel, escopo_tipo, escopo_id):
        raise Conflict("O grupo já está mapeado para este papel neste escopo.")
    membros_ativos = await membros.membros_ativos(grupo_id)
    if quem.id in membros_ativos:
        # Segregação de funções (R2.5): o grupo é o recurso do `acesso.negado` (R4.6).
        raise AcessoNegado(PERMISSAO, Recurso(tipo="grupo", id=str(grupo_id)))
    mapeamento = MapeamentoDeGrupo(
        id=novo_id,
        grupo_id=grupo_id,
        papel=papel,
        scope_type=escopo_tipo,
        scope_id=escopo_id,
        criado_por=quem.id,
    )
    await mapeamentos.inserir(mapeamento)
    await registrar(
        auditoria,
        acao="mapeamento.criado",
        ator=ator,
        entidade=Entidade(tipo=ENTIDADE, id=str(mapeamento.id)),
        metadados={**_campos(mapeamento), "criado_por": str(quem.id)},
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
    quem: UsuarioAtual,
    ator: Ator,
    mapeamentos: RepositorioDeMapeamentos,
    atribuicoes: RepositorioDeAtribuicoes,
    permissoes: RepositorioDePermissoes,
    auditoria: AuditStore,
) -> None:
    """Remove o mapeamento e as atribuições derivadas dele (R3.2); as diretas ficam (R3.3).

    `NotFound` (404) se ele não existe.
    """
    mapeamento = await mapeamentos.obter(mapeamento_id)
    if mapeamento is None:
        raise NotFound("Mapeamento não encontrado.")
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
        metadados={**_campos(mapeamento), "removido_por": str(quem.id)},
    )


async def listar_mapeamentos(*, mapeamentos: RepositorioDeMapeamentos) -> list[MapeamentoDeGrupo]:
    return list(await mapeamentos.listar())


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
        user_id=usuario_id,
        papel=mapeamento.papel,
        scope_type=mapeamento.scope_type,
        scope_id=mapeamento.scope_id,
        origin="group",
        valid_until=None,
        granted_by=None,
        group_mapping_id=mapeamento.id,
    )
    await atribuicoes.inserir(derivada)
    await permissoes.invalidar(usuario_id)
    await registrar(
        auditoria,
        acao="papel.atribuido",
        ator=ator,
        entidade=Entidade(tipo="usuario", id=str(usuario_id)),
        metadados=_campos_da_derivada(derivada),
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
    await permissoes.invalidar(derivada.user_id)
    await registrar(
        auditoria,
        acao="papel.removido",
        ator=ator,
        entidade=Entidade(tipo="usuario", id=str(derivada.user_id)),
        metadados=_campos_da_derivada(derivada),
    )


def _campos(mapeamento: MapeamentoDeGrupo) -> dict[str, str | None]:
    """Os campos do mapeamento na auditoria, como valores JSON."""
    return {
        "mapeamento_id": str(mapeamento.id),
        "grupo_id": str(mapeamento.grupo_id),
        "papel": mapeamento.papel,
        "escopo_tipo": mapeamento.scope_type,
        "escopo_id": mapeamento.scope_id,
    }


def _campos_da_derivada(derivada: Atribuicao) -> dict[str, str | None]:
    """Os campos da atribuição derivada na auditoria, como os da direta (R2.4), com a origem e o
    mapeamento que a gerou no lugar de quem concedeu."""
    return {
        "atribuicao_id": str(derivada.id),
        "papel": derivada.papel,
        "escopo_tipo": derivada.scope_type,
        "escopo_id": derivada.scope_id,
        "origem": derivada.origin,
        "mapeamento_id": str(derivada.group_mapping_id),
    }
