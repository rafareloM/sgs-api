"""Consultas do diretório espelhado para o Admin TI (spec 004, T4; design § Rotas): as
execuções da sincronização (R1.9) e os grupos com os membros ativos (R1.14)."""

from dataclasses import dataclass
from uuid import UUID

from src.core.errors import NotFound
from src.modules.identity.domain.espelho_diretorio import GroupListing, OrigemDeGrupo, SyncRun
from src.modules.identity.domain.ports import DirectoryRepository


@dataclass(frozen=True)
class PaginaDeExecucoes:
    itens: tuple[SyncRun, ...]
    total: int


@dataclass(frozen=True)
class PaginaDeGrupos:
    itens: tuple[GroupListing, ...]
    total: int


async def listar_execucoes(
    *, limite: int, deslocamento: int, repositorio: DirectoryRepository
) -> PaginaDeExecucoes:
    itens, total = await repositorio.list_runs(limit=limite, offset=deslocamento)
    return PaginaDeExecucoes(itens=itens, total=total)


async def obter_execucao(execucao_id: UUID, *, repositorio: DirectoryRepository) -> SyncRun:
    """`NotFound` (404) se a execução não existe."""
    execucao = await repositorio.get_run(execucao_id)
    if execucao is None:
        raise NotFound("Execução não encontrada.")
    return execucao


async def listar_grupos(
    *,
    origem: OrigemDeGrupo | None,
    ativo: bool,
    busca: str | None,
    limite: int,
    deslocamento: int,
    repositorio: DirectoryRepository,
) -> PaginaDeGrupos:
    itens, total = await repositorio.list_groups(
        source=origem, active=ativo, search=busca, limit=limite, offset=deslocamento
    )
    return PaginaDeGrupos(itens=itens, total=total)
