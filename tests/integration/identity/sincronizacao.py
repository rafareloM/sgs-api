"""Ajudante dos testes da sincronização: as transações do caso de uso sobre o banco de teste."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from src.modules.access.infrastructure.repository import (
    SqlRepositorioDeAtribuicoes,
    SqlRepositorioDeMapeamentos,
    SqlRepositorioDePermissoes,
)
from src.modules.audit.infrastructure.repository import SqlAuditStore
from src.modules.identity.application.sincronizacao import (
    RepositoriosDaSincronizacao,
    Transacoes,
)
from src.modules.identity.infrastructure.directory_repository import SqlDirectoryRepository
from tests.integration.acesso import Sessoes


def transacoes_de(sessoes: Sessoes) -> Transacoes:
    @asynccontextmanager
    async def abrir() -> AsyncIterator[RepositoriosDaSincronizacao]:
        async with sessoes() as sessao, sessao.begin():
            yield RepositoriosDaSincronizacao(
                diretorio=SqlDirectoryRepository(sessao),
                mapeamentos=SqlRepositorioDeMapeamentos(sessao),
                atribuicoes=SqlRepositorioDeAtribuicoes(sessao),
                permissoes=SqlRepositorioDePermissoes(sessao),
                auditoria=SqlAuditStore(sessao),
            )

    return abrir
