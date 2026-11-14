"""Log do banco só para leitura pela aplicação; dono e função do log com privilégio mínimo (011/T7).

As escritas são tentadas pelo login da API (membro do `sgs_app`), o que uma credencial vazada da
aplicação conseguiria fazer; o catálogo é consultado pelo dono do banco.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.integration.postgres import LOGIN_DA_API, BancoDeTeste, motor
from tests.integration.registry.cadastro import inserir_unidade

SEM_PRIVILEGIO = "42501"  # SQLSTATE insufficient_privilege

ESCRITAS = {
    "insert": (
        "INSERT INTO {tabela} (table_name, operation, row_id, changed_columns, db_user, via_api,"
        " txid) VALUES ('health_units', 'DELETE', gen_random_uuid(), '{{}}', 'sgs', true, 1)"
    ),
    "update": "UPDATE {tabela} SET via_api = true, db_user = 'sgs_api'",
    "delete": "DELETE FROM {tabela}",
    "truncate": "TRUNCATE {tabela}",
}
# A tabela-mãe e a partição DEFAULT: escrever direto nela também não pode. As mensais, onde os
# registros caem desde a 011/T8, ficam sem privilégio nenhum (test_particoes.py).
TABELAS = ("db_change_log", "db_change_log_default")


async def _registros(banco: BancoDeTeste) -> list[tuple[str, str, bool]]:
    engine = motor(banco.url_dono)
    async with engine.connect() as conexao:
        linhas = await conexao.execute(
            text("SELECT table_name, operation, via_api FROM db_change_log ORDER BY id")
        )
        registros = [tuple(linha) for linha in linhas]
    await engine.dispose()
    return registros


@pytest.mark.parametrize("tabela", TABELAS)
@pytest.mark.parametrize("escrita", ESCRITAS.values(), ids=ESCRITAS.keys())
async def test_login_da_api_nao_escreve_no_log(
    banco: BancoDeTeste, escrita: str, tabela: str
) -> None:
    """011/R7.6: nem incluir, nem alterar, nem apagar, nem truncar registros diretamente."""
    api = motor(banco.url_api)
    async with api.begin() as conexao:
        await inserir_unidade(conexao, "CAPS José Lucena")
    antes = await _registros(banco)

    with pytest.raises(DBAPIError) as erro:
        async with api.begin() as conexao:
            await conexao.execute(text(escrita.format(tabela=tabela)))
    await api.dispose()

    assert getattr(erro.value.orig, "sqlstate", None) == SEM_PRIVILEGIO
    assert await _registros(banco) == antes == [("health_units", "INSERT", True)]


async def test_login_da_api_le_o_log(banco: BancoDeTeste) -> None:
    """011/R7.6: a aplicação lê o log (para a consulta do Auditor, R7.7)."""
    api = motor(banco.url_api)
    async with api.begin() as conexao:
        unidade = await inserir_unidade(conexao, "CAPS José Lucena")
    async with api.connect() as conexao:
        linhas = await conexao.execute(text("SELECT row_id, operation FROM db_change_log"))
        lidos = [tuple(linha) for linha in linhas]
    await api.dispose()

    assert lidos == [(unidade, "INSERT")]


async def test_log_e_funcao_do_trigger_pertencem_ao_papel_dono(banco: BancoDeTeste) -> None:
    """011/R10.2: a função que roda com privilégio do dono (SECURITY DEFINER) e o log que ela
    grava pertencem ao `sgs_owner`, sem login nem superusuário (011/T3).
    """
    engine = motor(banco.url_dono)
    async with engine.connect() as conexao:
        linha = await conexao.execute(
            text(
                "SELECT"
                " (SELECT pg_get_userbyid(relowner) FROM pg_class"
                "  WHERE oid = 'db_change_log'::regclass),"
                " (SELECT pg_get_userbyid(relowner) FROM pg_class"
                "  WHERE oid = 'db_change_log_default'::regclass),"
                " (SELECT pg_get_userbyid(proowner) FROM pg_proc"
                "  WHERE oid = 'trg_registry_change_log()'::regprocedure),"
                " (SELECT prosecdef FROM pg_proc"
                "  WHERE oid = 'trg_registry_change_log()'::regprocedure)"
            )
        )
        dono_do_log, dono_da_particao, dono_da_funcao, definer = linha.one()
    await engine.dispose()

    assert (dono_do_log, dono_da_particao, dono_da_funcao) == ("sgs_owner",) * 3
    assert definer is True


async def test_so_o_trigger_executa_a_funcao_do_log(banco: BancoDeTeste) -> None:
    """011/R10.1: nem PUBLIC nem a aplicação executam a função; o trigger dispara sem isso
    (as escritas do login da API em test_log_banco.py são registradas).
    """
    engine = motor(banco.url_dono)
    async with engine.connect() as conexao:
        linha = await conexao.execute(
            text(
                "SELECT has_function_privilege('public', 'trg_registry_change_log()', 'EXECUTE'),"
                " has_function_privilege('sgs_app', 'trg_registry_change_log()', 'EXECUTE'),"
                " has_function_privilege(:login, 'trg_registry_change_log()', 'EXECUTE')"
            ),
            {"login": LOGIN_DA_API},
        )
        publico, aplicacao, login = linha.one()
    await engine.dispose()

    assert (publico, aplicacao, login) == (False, False, False)
