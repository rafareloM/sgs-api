"""Tabelas declaradas no código e migrações não divergem.

Se divergirem, `make migrate` (autogenerate) proporia mudanças indevidas, até apagar tabelas.
"""

from typing import Any

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Connection

from src.core.db import metadata
from src.modules.audit.infrastructure import tables  # noqa: F401 - registra as tabelas
from tests.integration.postgres import BancoDeTeste, motor


def _diferencas(conexao: Connection) -> list[Any]:
    contexto = MigrationContext.configure(conexao, opts={"compare_type": True})
    return list(compare_metadata(contexto, metadata))


async def test_migracoes_e_tabelas_do_codigo_nao_divergem(banco: BancoDeTeste) -> None:
    engine = motor(banco.url_dono)
    async with engine.connect() as conexao:
        diferencas = await conexao.run_sync(_diferencas)
    await engine.dispose()

    assert diferencas == []
