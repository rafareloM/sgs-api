"""Sincronização do diretório LDAP (spec 004, T3; design § Fluxo, Sincronização).

1. `iniciar_sincronizacao` grava a execução `em_andamento` numa transação própria; o índice
   único parcial recusa uma segunda (R1.11).
2. `sincronizar` lê o diretório fora de transação e aplica o plano numa transação só (R1.5 a
   R1.9, R4.2). Qualquer falha desfaz tudo, e o `falhou` vai numa transação nova, com mensagem
   genérica; o detalhe fica só no log (R1.10, R1.13).
3. `marcar_interrompidas`, na subida da API, fecha como `falhou` o que ficou em andamento.

Quem chama dá as transações (`Transacoes`): cada uma abre a sessão, entrega os repositórios
ligados a ela e confirma na saída, ou desfaz se uma exceção passar.
"""

import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from src.modules.access.application.mapeamentos import recalcular_derivadas_do_usuario
from src.modules.access.domain.ports import (
    RepositorioDeAtribuicoes,
    RepositorioDeMapeamentos,
    RepositorioDePermissoes,
)
from src.modules.audit.application.registrar import Ator, AuditStore, Entidade, registrar
from src.modules.identity.domain.diretorio import (
    DirectoryPort,
    DirectorySnapshot,
    DirectoryUnavailable,
)
from src.modules.identity.domain.espelho_diretorio import OrigemDeGrupo, SyncConflict, SyncCounts
from src.modules.identity.domain.ports import DirectoryRepository
from src.modules.identity.domain.sincronizacao import Conflito, planejar
from src.modules.identity.domain.users import User, UserSource

ORIGEM: OrigemDeGrupo = "ldap"
ENTIDADE = "execucao_diretorio"
ERRO_DIRETORIO = "Diretório indisponível"
ERRO_GERAL = "Falha na sincronização"
ERRO_INTERROMPIDA = "Interrompida"
ERRO_RETRATO_VAZIO = "Diretório sem usuários; nada foi desativado"
# A subida da API fecha o que ficou em andamento: é o próprio sistema, não uma pessoa.
ATOR_DA_SUBIDA = Ator(tipo="sistema", origem="api")

_log = logging.getLogger("sgs_api.diretorio")


class RetratoVazio(Exception):  # noqa: N818 (sinal interno, vira a falha da execução)
    """Revisão da frente A, S5 (critério mínimo, 26/11/2026): um retrato sem nenhum usuário,
    com contas LDAP ativas no banco, é quase certamente um filtro ou base errados, e a R1.7
    desativaria todo mundo. A execução falha sem tocar em nada."""


@dataclass(frozen=True)
class RepositoriosDaSincronizacao:
    """Os repositórios de uma transação, todos sobre a mesma sessão."""

    diretorio: DirectoryRepository
    mapeamentos: RepositorioDeMapeamentos
    atribuicoes: RepositorioDeAtribuicoes
    permissoes: RepositorioDePermissoes
    auditoria: AuditStore


type Transacoes = Callable[[], AbstractAsyncContextManager[RepositoriosDaSincronizacao]]


async def iniciar_sincronizacao(
    execucao_id: UUID,
    *,
    triggered_by: UUID | None,
    transacoes: Transacoes,
    agora: Callable[[], datetime],
) -> bool:
    """Grava a execução `em_andamento`; `False` se já houver outra (R1.11)."""
    async with transacoes() as repos:
        return await repos.diretorio.start_run(
            execucao_id, triggered_by=triggered_by, agora=agora()
        )


async def sincronizar(
    execucao_id: UUID,
    *,
    diretorio: DirectoryPort,
    transacoes: Transacoes,
    ator: Ator,
    gerar_id: Callable[[], UUID],
    agora: Callable[[], datetime],
) -> None:
    """Lê o diretório, aplica o plano e fecha a execução (design § Fluxo, passos 2 a 5).

    Nunca levanta por falha do diretório ou da aplicação: a execução fica `falhou`.
    """
    try:
        retrato = await diretorio.snapshot()  # fora de transação (passo 2)
        async with transacoes() as repos:
            await _aplicar(execucao_id, retrato, repos, ator=ator, gerar_id=gerar_id, agora=agora)
    except DirectoryUnavailable:
        _log.warning("sincronização do diretório falhou: diretório indisponível")
        await _falhou(execucao_id, ERRO_DIRETORIO, transacoes=transacoes, ator=ator, agora=agora)
    except RetratoVazio:
        _log.warning("sincronização do diretório recusada: retrato sem usuários")
        await _falhou(
            execucao_id, ERRO_RETRATO_VAZIO, transacoes=transacoes, ator=ator, agora=agora
        )
    except Exception as erro:
        # Só o tipo do erro: a mensagem pode trazer dados do diretório (e-mails, nomes).
        _log.error("sincronização do diretório falhou: %s", type(erro).__name__)
        await _falhou(execucao_id, ERRO_GERAL, transacoes=transacoes, ator=ator, agora=agora)


async def marcar_interrompidas(*, transacoes: Transacoes, agora: Callable[[], datetime]) -> int:
    """Na subida, as execuções `em_andamento` viram `falhou` com "Interrompida" (passo 6). A
    API roda numa instância só (design § Riscos), então nenhuma delas está viva."""
    async with transacoes() as repos:
        ids = await repos.diretorio.fail_running_runs(ERRO_INTERROMPIDA, agora())
        for execucao_id in ids:
            await _auditar_falha(repos.auditoria, execucao_id, ERRO_INTERROMPIDA, ATOR_DA_SUBIDA)
    return len(ids)


async def _aplicar(
    execucao_id: UUID,
    retrato: DirectorySnapshot,
    repos: RepositoriosDaSincronizacao,
    *,
    ator: Ator,
    gerar_id: Callable[[], UUID],
    agora: Callable[[], datetime],
) -> None:
    instante = agora()
    estado = await repos.diretorio.local_state(ORIGEM)
    if not retrato.users and any(
        u.source is UserSource.LDAP and u.is_active for u in estado.usuarios
    ):
        raise RetratoVazio
    plano = planejar(retrato, estado)
    # `external_id` → id das contas `ldap` que já existem; as criadas entram abaixo.
    usuarios = {
        u.external_id: u.id
        for u in estado.usuarios
        if u.source is UserSource.LDAP and u.external_id is not None
    }

    # Grupos (passo 3.5).
    grupos: dict[str, UUID] = {}
    grupos_criados = grupos_atualizados = 0
    dados_dos_grupos = [*plano.grupos_criacoes, *(a.dados for a in plano.grupos_atualizacoes)]
    for dado_do_grupo in dados_dos_grupos:
        grupo = await repos.diretorio.upsert_group(
            ORIGEM, dado_do_grupo.external_id, dado_do_grupo.name, instante
        )
        grupos[dado_do_grupo.external_id] = grupo.id
        if grupo.created:
            grupos_criados += 1
        else:
            grupos_atualizados += 1
    grupos_desativados = await repos.diretorio.deactivate_groups_except(
        ORIGEM, set(grupos), instante
    )

    # Usuários (passos 3.3 e 3.4).
    for dado in plano.criacoes:
        usuario = User(
            id=gerar_id(),
            username=dado.login,
            display_name=dado.display_name,
            source=UserSource.LDAP,
            email=dado.email,
            external_id=dado.external_id,
        )
        await repos.diretorio.add_synced_user(usuario, instante)
        usuarios[dado.external_id] = usuario.id
    for atualizacao in plano.atualizacoes:
        dado = atualizacao.dados
        # Valida nome e e-mail como na criação, antes de gravar.
        conferido = User(
            id=atualizacao.usuario_id,
            username=dado.login,
            display_name=dado.display_name,
            source=UserSource.LDAP,
            email=atualizacao.email,
            external_id=dado.external_id,
        )
        await repos.diretorio.update_synced_user(
            atualizacao.usuario_id,
            display_name=conferido.display_name,
            email=conferido.email,
            agora=instante,
        )
    await repos.diretorio.deactivate_users(set(plano.desativacoes), instante)

    # Associações e derivadas da 003 (passos 3.6 e 3.7).
    for external_id in sorted(plano.recalcular):
        usuario_id = usuarios[external_id]
        do_usuario = {grupos[g] for g in plano.associacoes.get(external_id, frozenset())}
        await repos.diretorio.replace_user_groups(usuario_id, ORIGEM, do_usuario)
        # O recálculo recebe todos os grupos atuais do usuário, de todas as origens (003/R3.2).
        outros = await repos.diretorio.groups_of_user(usuario_id, "oidc")
        await recalcular_derivadas_do_usuario(
            usuario_id,
            frozenset(do_usuario) | outros,
            ator=ator,
            mapeamentos=repos.mapeamentos,
            atribuicoes=repos.atribuicoes,
            permissoes=repos.permissoes,
            auditoria=repos.auditoria,
            gerar_id=gerar_id,
        )

    # Conflitos (passo 4) e fechamento (passo 3.8).
    for conflito in plano.conflitos:
        await _auditar_conflito(repos.auditoria, execucao_id, conflito, ator)
    contagens = SyncCounts(
        users_created=len(plano.criacoes),
        users_updated=len(plano.atualizacoes),
        users_deactivated=len(plano.desativacoes),
        groups_created=grupos_criados,
        groups_updated=grupos_atualizados,
        groups_deactivated=grupos_desativados,
    )
    await repos.diretorio.finish_run(
        execucao_id,
        "concluida",
        instante,
        counts=contagens,
        conflicts=tuple(
            SyncConflict(c.tipo.value, c.external_id, c.usuario_existente_id)
            for c in plano.conflitos
        ),
    )
    await registrar(
        repos.auditoria,
        acao="diretorio.sincronizado",
        ator=ator,
        entidade=Entidade(tipo=ENTIDADE, id=str(execucao_id)),
        metadados={
            "usuarios": {
                "criados": contagens.users_created,
                "atualizados": contagens.users_updated,
                "desativados": contagens.users_deactivated,
            },
            "grupos": {
                "criados": contagens.groups_created,
                "atualizados": contagens.groups_updated,
                "desativados": contagens.groups_deactivated,
            },
            "conflitos": len(plano.conflitos),
        },
    )


async def _falhou(
    execucao_id: UUID,
    erro: str,
    *,
    transacoes: Transacoes,
    ator: Ator,
    agora: Callable[[], datetime],
) -> None:
    try:
        async with transacoes() as repos:
            await repos.diretorio.finish_run(execucao_id, "falhou", agora(), error=erro)
            await _auditar_falha(repos.auditoria, execucao_id, erro, ator)
    except Exception as falha:
        # Não deixa a tarefa em segundo plano morrer com exceção. A execução fica em andamento
        # até a próxima subida da API, que a fecha como "Interrompida" (passo 6).
        _log.error("execução do diretório não foi fechada: %s", type(falha).__name__)


async def _auditar_falha(auditoria: AuditStore, execucao_id: UUID, erro: str, ator: Ator) -> None:
    await registrar(
        auditoria,
        acao="diretorio.sincronizado",
        ator=ator,
        entidade=Entidade(tipo=ENTIDADE, id=str(execucao_id)),
        metadados={"erro": erro},
        resultado="failure",
        categoria="erro_interno",
    )


async def _auditar_conflito(
    auditoria: AuditStore, execucao_id: UUID, conflito: Conflito, ator: Ator
) -> None:
    """Sem e-mail nem nome: só os ids (LGPD, design § Rotas)."""
    existente = conflito.usuario_existente_id
    await registrar(
        auditoria,
        acao="diretorio.conflito",
        ator=ator,
        entidade=Entidade(tipo=ENTIDADE, id=str(execucao_id)),
        metadados={
            "execucao_id": str(execucao_id),
            "tipo": conflito.tipo.value,
            "external_id": conflito.external_id,
            "usuario_existente_id": None if existente is None else str(existente),
        },
        resultado="denied",
        categoria="conflito",
    )
