"""Desativação de unidade pelo procedimento do banco: `sp_deactivate_unit` (011/T6).

SQL direto pelo login da API (membro de `sgs_app`), como o caso de uso da 006 vai chamar
(design da 011 § Fluxo, Desativação). A rota e a auditoria são da 011/T16 com a 006/T6.
"""

from uuid import UUID

import pytest
from sqlalchemy import Row, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from src.core.ids import uuid7
from tests.integration.postgres import BancoDeTeste, motor
from tests.integration.registry.cadastro import inserir_unidade

DESATIVAR = text("CALL sp_deactivate_unit(CAST(:id AS uuid), NULL, NULL)")


async def _desativar(conexao: AsyncConnection, unidade: UUID) -> Row[tuple[str, int]]:
    resultado = await conexao.execute(DESATIVAR, {"id": unidade})
    return resultado.one()


async def _status_e_versao(engine: AsyncEngine, unidade: UUID) -> tuple[str, int]:
    async with engine.connect() as conexao:
        linha = await conexao.execute(
            text("SELECT status, version FROM health_units WHERE id = :id"), {"id": unidade}
        )
        status, versao = linha.one()
    return str(status), int(versao)


async def _linha(engine: AsyncEngine, unidade: UUID) -> dict[str, object]:
    """A unidade inteira, para conferir que nada mudou (inclusive `updated_at`)."""
    async with engine.connect() as conexao:
        linha = await conexao.execute(
            text("SELECT * FROM health_units WHERE id = :id"), {"id": unidade}
        )
        return dict(linha.mappings().one())


async def test_desativa_unidade_ativa_e_devolve_status_anterior_e_versao_nova(
    banco: BancoDeTeste,
) -> None:
    """011/R6.1: pelo login da API, o CALL desativa e devolve o status anterior e a versão nova."""
    engine = motor(banco.url_api)
    async with engine.begin() as conexao:
        unidade = await inserir_unidade(conexao, "CAPS Galdino Loreto")
    async with engine.begin() as conexao:
        devolvido = await _desativar(conexao, unidade)
    gravado = await _status_e_versao(engine, unidade)
    await engine.dispose()

    assert (devolvido.o_previous_status, devolvido.o_version) == ("ativa", 2)
    assert gravado == ("inativa", 2)


async def test_unidade_inexistente_levanta_o_sqlstate_proprio(banco: BancoDeTeste) -> None:
    """011/R6.3: o SQLSTATE `SGS01` é o que o repositório da 006 vai traduzir em 404."""
    engine = motor(banco.url_api)
    try:
        with pytest.raises(DBAPIError) as erro:
            async with engine.begin() as conexao:
                await _desativar(conexao, uuid7())
    finally:
        await engine.dispose()

    assert getattr(erro.value.orig, "sqlstate", None) == "SGS01"


async def test_unidade_ja_inativa_fica_como_esta_e_a_versao_nao_muda(banco: BancoDeTeste) -> None:
    """011/R6.4: a segunda desativação devolve `inativa` e a mesma versão, sem tocar na linha."""
    engine = motor(banco.url_api)
    async with engine.begin() as conexao:
        unidade = await inserir_unidade(conexao, "CAPS Espaço Azul")
    async with engine.begin() as conexao:
        await _desativar(conexao, unidade)
    antes = await _linha(engine, unidade)
    async with engine.begin() as conexao:
        devolvido = await _desativar(conexao, unidade)
    depois = await _linha(engine, unidade)
    await engine.dispose()

    assert (devolvido.o_previous_status, devolvido.o_version) == ("inativa", 2)
    assert depois == antes


async def test_desativacao_desfeita_junto_com_a_transacao_de_quem_chama(
    banco: BancoDeTeste,
) -> None:
    """011/R6.2: sem COMMIT próprio, a desativação vale ou cai junto com a auditoria da API."""
    engine = motor(banco.url_api)
    async with engine.begin() as conexao:
        unidade = await inserir_unidade(conexao, "CAPS Livremente")
    async with engine.connect() as conexao:
        await _desativar(conexao, unidade)
        await conexao.rollback()
    gravado = await _status_e_versao(engine, unidade)
    await engine.dispose()

    assert gravado == ("ativa", 1)


async def test_so_a_aplicacao_executa_o_procedimento(banco: BancoDeTeste) -> None:
    """011/R10.1: PUBLIC sem EXECUTE; `sgs_app` com EXECUTE."""
    engine = motor(banco.url_dono)
    async with engine.connect() as conexao:
        linha = await conexao.execute(
            text(
                "SELECT has_function_privilege('public', CAST(:procedimento AS regprocedure),"
                " 'EXECUTE'),"
                " has_function_privilege('sgs_app', CAST(:procedimento AS regprocedure),"
                " 'EXECUTE')"
            ),
            # Na assinatura do regprocedure só entram os parâmetros de entrada.
            {"procedimento": "sp_deactivate_unit(uuid)"},
        )
        publico, aplicacao = linha.one()
    await engine.dispose()

    assert (publico, aplicacao) == (False, True)
