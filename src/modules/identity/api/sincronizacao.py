"""Ligação da sincronização do diretório aos repositórios de `app.state` (spec 004, T3).

A rota (T4), o agendador (T9) e a subida da API usam as mesmas transações: cada uma abre uma
sessão, entrega os repositórios ligados a ela e confirma na saída, ou desfaz se uma exceção
passar.
"""

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any

from src.modules.identity.application.sincronizacao import RepositoriosDaSincronizacao


def transacoes_da_sincronizacao(
    estado: Any,
) -> Callable[[], AbstractAsyncContextManager[RepositoriosDaSincronizacao]]:
    @asynccontextmanager
    async def abrir() -> AsyncIterator[RepositoriosDaSincronizacao]:
        async with estado.sessoes() as sessao, sessao.begin():
            yield RepositoriosDaSincronizacao(
                diretorio=estado.repositorio_do_diretorio(sessao),
                mapeamentos=estado.repositorio_de_mapeamentos(sessao),
                atribuicoes=estado.repositorio_de_atribuicoes(sessao),
                permissoes=estado.repositorio_de_permissoes(sessao),
                auditoria=estado.auditoria(sessao),
            )

    return abrir
