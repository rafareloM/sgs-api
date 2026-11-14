"""Versão da unidade mantida pelo banco: `trg_health_units_version` (011/T5).

SQL direto, sem a API no meio: o trigger vale para qualquer escrita, seja da aplicação (login da
API) ou de fora dela (superusuário, o dono do banco de teste).
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.postgres import BancoDeTeste, motor
from tests.integration.registry.cadastro import inserir_unidade


async def _versao_e_atualizacao(engine: AsyncEngine, unidade: UUID) -> tuple[int, datetime]:
    async with engine.connect() as conexao:
        linha = await conexao.execute(
            text("SELECT version, updated_at FROM health_units WHERE id = :id"), {"id": unidade}
        )
        versao, atualizada_em = linha.one()
    return int(versao), atualizada_em


async def test_update_direto_incrementa_versao_e_data_de_atualizacao(banco: BancoDeTeste) -> None:
    """011/R8.1: alteração direta no banco (fora da API) invalida a versão em mãos."""
    engine = motor(banco.url_dono)
    async with engine.begin() as conexao:
        unidade = await inserir_unidade(conexao, "CAPS José Lucena")
    versao_antes, atualizada_antes = await _versao_e_atualizacao(engine, unidade)

    async with engine.begin() as conexao:
        await conexao.execute(
            text("UPDATE health_units SET phone = '8133551234' WHERE id = :id"), {"id": unidade}
        )
    versao_depois, atualizada_depois = await _versao_e_atualizacao(engine, unidade)
    await engine.dispose()

    assert (versao_antes, versao_depois) == (1, 2)
    assert atualizada_depois > atualizada_antes


async def test_mudanca_so_nas_pendencias_nao_incrementa_a_versao(banco: BancoDeTeste) -> None:
    """011/R8.2: a contagem de pendências (mantida pela 007) não invalida a versão em mãos."""
    engine = motor(banco.url_api)
    async with engine.begin() as conexao:
        unidade = await inserir_unidade(conexao, "USF Upinha Dia Vila Arraes")
    antes = await _versao_e_atualizacao(engine, unidade)

    async with engine.begin() as conexao:
        await conexao.execute(
            text("UPDATE health_units SET pending_issues = 3 WHERE id = :id"), {"id": unidade}
        )
    depois = await _versao_e_atualizacao(engine, unidade)
    await engine.dispose()

    assert depois == antes


async def test_so_o_trigger_executa_a_funcao_de_versao(banco: BancoDeTeste) -> None:
    """011/R10.1: nem PUBLIC nem a aplicação têm EXECUTE na função do trigger."""
    engine = motor(banco.url_dono)
    async with engine.connect() as conexao:
        linha = await conexao.execute(
            text(
                "SELECT has_function_privilege('public', 'trg_health_units_version()', 'EXECUTE'),"
                " has_function_privilege('sgs_app', 'trg_health_units_version()', 'EXECUTE')"
            )
        )
        publico, aplicacao = linha.one()
    await engine.dispose()

    assert (publico, aplicacao) == (False, False)


async def test_escrita_da_aplicacao_incrementa_a_versao_sem_execute_na_funcao(
    banco: BancoDeTeste,
) -> None:
    """011/R8.1 e R10.1: pelo login da API, que não executa a função, o trigger dispara igual."""
    engine = motor(banco.url_api)
    async with engine.begin() as conexao:
        unidade = await inserir_unidade(conexao, "Policlínica Amaury Coutinho")
    async with engine.begin() as conexao:
        await conexao.execute(
            text("UPDATE health_units SET name = 'Policlínica Amaury de Medeiros' WHERE id = :id"),
            {"id": unidade},
        )
    versao, _ = await _versao_e_atualizacao(engine, unidade)
    await engine.dispose()

    assert versao == 2
