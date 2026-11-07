"""Partições mensais do log do banco: `sp_ensure_monthly_partitions` (011/T8).

SQL direto, sem a API no meio: o procedimento é chamado pelo dono do banco (o superusuário que
migra, como o `sgs` do compose) e, para o teste de privilégio, pelo login da API. Os meses
esperados vêm do relógio do Python, em UTC, não do banco.
"""

import os
import subprocess
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection

from src.core.db import PROJECT_ROOT
from tests.integration.postgres import LOGIN_DA_API, BancoDeTeste, motor
from tests.integration.registry.cadastro import inserir_unidade

ASSINATURA = "sp_ensure_monthly_partitions(regclass, integer)"
DEFAULT = "db_change_log_default"
SEM_PRIVILEGIO = "42501"  # SQLSTATE insufficient_privilege
VALOR_INVALIDO = "22023"  # SQLSTATE invalid_parameter_value


def _mes(deslocamento: int) -> date:
    """Primeiro dia do mês `deslocamento` meses depois do atual, em UTC."""
    hoje = datetime.now(UTC).date()
    indice = hoje.year * 12 + hoje.month - 1 + deslocamento
    return date(indice // 12, indice % 12 + 1, 1)


def _nome(deslocamento: int) -> str:
    mes = _mes(deslocamento)
    return f"db_change_log_y{mes.year:04d}m{mes.month:02d}"


def _limites(deslocamento: int) -> str:
    """Limites da partição como o PostgreSQL os devolve com `TimeZone = UTC`."""
    de, ate = _mes(deslocamento), _mes(deslocamento + 1)
    return f"FOR VALUES FROM ('{de} 00:00:00+00') TO ('{ate} 00:00:00+00')"


def _esperadas(*deslocamentos: int) -> dict[str, str]:
    return {DEFAULT: "DEFAULT"} | {_nome(d): _limites(d) for d in deslocamentos}


async def _particoes(conexao: AsyncConnection) -> dict[str, str]:
    """Partições de `db_change_log`: nome e limites."""
    await conexao.execute(text("SET TIME ZONE 'UTC'"))
    linhas = await conexao.execute(
        text(
            "SELECT c.relname, pg_get_expr(c.relpartbound, c.oid) FROM pg_inherits i"
            " JOIN pg_class c ON c.oid = i.inhrelid"
            " WHERE i.inhparent = 'db_change_log'::regclass"
        )
    )
    return dict(linhas.all())


async def _gravar_no_log(conexao: AsyncConnection, quando: datetime) -> None:
    """Um registro do log com data escolhida, gravado direto pelo superusuário."""
    await conexao.execute(
        text(
            "INSERT INTO db_change_log (occurred_at, table_name, operation, row_id,"
            " changed_columns, db_user, via_api, txid)"
            " VALUES (:quando, 'health_units', 'UPDATE', gen_random_uuid(), '{}', current_user,"
            " false, txid_current())"
        ),
        {"quando": quando},
    )


async def _registros_por_particao(conexao: AsyncConnection) -> dict[str, int]:
    linhas = await conexao.execute(
        text("SELECT tableoid::regclass::text, count(*) FROM db_change_log GROUP BY 1")
    )
    return dict(linhas.all())


async def test_migracao_deixa_doze_meses_a_frente(banco: BancoDeTeste) -> None:
    """011/R6.7: depois das migrações, há partição do mês atual até 12 meses à frente, cada uma
    do primeiro instante do mês ao primeiro do mês seguinte, em UTC, além da DEFAULT.
    """
    engine = motor(banco.url_dono)
    async with engine.connect() as conexao:
        particoes = await _particoes(conexao)
    await engine.dispose()

    assert particoes == _esperadas(*range(13))


def test_chamada_da_migracao_sai_no_modo_offline(tmp_path: Path) -> None:
    """011/R6.7 e R11.3: o `CALL` com 12 meses está no DDL que o `alembic upgrade --sql` imprime
    (base do `make sql-bd`), depois do procedimento.
    """
    ambiente = {
        nome: valor for nome, valor in os.environ.items() if not nome.startswith("DATABASE")
    }
    ambiente["PYTHONUTF8"] = "1"  # no Windows, a saída do processo filho sairia em cp1252

    resultado = subprocess.run(  # noqa: S603 (comando fixo, sem entrada de usuário)
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            str(PROJECT_ROOT / "alembic.ini"),
            "upgrade",
            "0011_07:0011_08",
            "--sql",
        ],
        cwd=tmp_path,
        env=ambiente,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )

    assert resultado.returncode == 0, resultado.stderr
    procedimento = resultado.stdout.index("CREATE PROCEDURE sp_ensure_monthly_partitions(")
    chamada = resultado.stdout.index("\nCALL sp_ensure_monthly_partitions('db_change_log', 12);")
    assert procedimento < chamada


async def test_procedimento_cria_os_meses_que_faltam(banco: BancoDeTeste) -> None:
    """011/R6.5: do mês atual até N meses à frente, cria cada mês sem partição (um buraco no
    meio e os meses além dos 12 da migração) e deixa os que já existem.
    """
    engine = motor(banco.url_dono)
    async with engine.begin() as conexao:
        await conexao.execute(text(f"DROP TABLE {_nome(3)}"))
    async with engine.begin() as conexao:
        await conexao.execute(text("CALL sp_ensure_monthly_partitions('db_change_log', 15)"))
    async with engine.connect() as conexao:
        particoes = await _particoes(conexao)
    await engine.dispose()

    assert particoes == _esperadas(*range(16))


async def test_procedimento_nao_apaga_nenhuma_particao(banco: BancoDeTeste) -> None:
    """011/R6.5: nem a partição de um mês passado nem as que passam do horizonte pedido somem,
    e o registro gravado numa delas continua lá.
    """
    passado = _mes(-2)
    engine = motor(banco.url_dono)
    async with engine.begin() as conexao:
        await conexao.execute(
            text(
                f"CREATE TABLE {_nome(-2)} PARTITION OF db_change_log"
                f" FOR VALUES FROM ('{passado}+00') TO ('{_mes(-1)}+00')"
            )
        )
        await _gravar_no_log(conexao, datetime(passado.year, passado.month, 15, tzinfo=UTC))
    async with engine.connect() as conexao:
        antes = await _particoes(conexao)
    async with engine.begin() as conexao:
        await conexao.execute(text("CALL sp_ensure_monthly_partitions('db_change_log', 1)"))
    async with engine.connect() as conexao:
        depois = await _particoes(conexao)
        registros = await _registros_por_particao(conexao)
    await engine.dispose()

    assert depois == antes == _esperadas(-2, *range(13))
    assert registros == {_nome(-2): 1}


async def test_mes_com_registro_na_default_e_pulado_com_aviso(banco: BancoDeTeste) -> None:
    """011/R6.6: um mês sem partição que já tem registro na DEFAULT fica sem partição, com um
    aviso que nomeia o mês; o registro não sai da DEFAULT, e os outros meses que faltam são
    criados.
    """
    ocupado = _mes(2)
    engine = motor(banco.url_dono)
    async with engine.begin() as conexao:
        await conexao.execute(text(f"DROP TABLE {_nome(2)}"))
        await conexao.execute(text(f"DROP TABLE {_nome(5)}"))
        await _gravar_no_log(conexao, datetime(ocupado.year, ocupado.month, 10, tzinfo=UTC))
    avisos: list[str] = []
    async with engine.begin() as conexao:
        # Avisos e notícias do servidor chegam ao asyncpg fora do resultado da instrução.
        bruta = await conexao.get_raw_connection()
        asyncpg_conexao = bruta.driver_connection
        assert asyncpg_conexao is not None
        asyncpg_conexao.add_log_listener(
            lambda _conexao, mensagem: avisos.append(f"{mensagem.severity_en}: {mensagem.message}")
        )
        await conexao.execute(text("CALL sp_ensure_monthly_partitions('db_change_log', 12)"))
    async with engine.connect() as conexao:
        particoes = await _particoes(conexao)
        registros = await _registros_por_particao(conexao)
    await engine.dispose()

    assert particoes == _esperadas(*(d for d in range(13) if d != 2))
    assert registros == {DEFAULT: 1}
    assert [aviso for aviso in avisos if aviso.startswith("WARNING")] == [
        f"WARNING: db_change_log: o mês {ocupado:%Y-%m} já tem registros na partição {DEFAULT};"
        f" a partição {_nome(2)} não foi criada e os registros ficam onde estão"
    ]


ARGUMENTOS_INVALIDOS = {
    "meses-negativos": "'db_change_log', -1",
    "tabela-sem-particao": "'health_units', 12",
}


@pytest.mark.parametrize("argumentos", ARGUMENTOS_INVALIDOS.values(), ids=ARGUMENTOS_INVALIDOS)
async def test_argumentos_invalidos_sao_recusados(banco: BancoDeTeste, argumentos: str) -> None:
    """011/R6.5: horizonte negativo ou tabela que não é particionada por intervalo param o
    procedimento antes de qualquer criação.
    """
    engine = motor(banco.url_dono)
    with pytest.raises(DBAPIError) as erro:
        async with engine.begin() as conexao:
            await conexao.execute(text(f"CALL sp_ensure_monthly_partitions({argumentos})"))
    await engine.dispose()

    assert getattr(erro.value.orig, "sqlstate", None) == VALOR_INVALIDO


async def test_login_da_api_nao_executa_o_procedimento(banco: BancoDeTeste) -> None:
    """011/R10.1: nem o login da API, nem o `sgs_app`, nem PUBLIC executam o procedimento, que
    cria tabelas com o privilégio do dono do log; a tentativa não cria nada.
    """
    dono = motor(banco.url_dono)
    async with dono.begin() as conexao:
        await conexao.execute(text(f"DROP TABLE {_nome(4)}"))
    api = motor(banco.url_api)
    with pytest.raises(DBAPIError) as erro:
        async with api.begin() as conexao:
            await conexao.execute(text("CALL sp_ensure_monthly_partitions('db_change_log', 12)"))
    await api.dispose()
    async with dono.connect() as conexao:
        linha = await conexao.execute(
            text(
                "SELECT has_function_privilege('public', :assinatura, 'EXECUTE'),"
                " has_function_privilege('sgs_app', :assinatura, 'EXECUTE'),"
                " has_function_privilege(:login, :assinatura, 'EXECUTE')"
            ),
            {"assinatura": ASSINATURA, "login": LOGIN_DA_API},
        )
        privilegios = tuple(linha.one())
        particoes = await _particoes(conexao)
    await dono.dispose()

    assert getattr(erro.value.orig, "sqlstate", None) == SEM_PRIVILEGIO
    assert privilegios == (False, False, False)
    assert particoes == _esperadas(*(d for d in range(13) if d != 4))


async def test_procedimento_e_particoes_pertencem_ao_papel_dono(banco: BancoDeTeste) -> None:
    """011/R10.2 e R7.6: o procedimento SECURITY DEFINER e as partições que ele cria pertencem
    ao `sgs_owner`; o login da API não tem privilégio direto em nenhuma partição (lê o log só
    pela tabela-mãe).
    """
    engine = motor(banco.url_dono)
    async with engine.connect() as conexao:
        rotina = await conexao.execute(
            text(
                "SELECT pg_get_userbyid(proowner), prosecdef FROM pg_proc"
                " WHERE oid = CAST(:assinatura AS regprocedure)"
            ),
            {"assinatura": ASSINATURA},
        )
        dono_da_rotina, definer = rotina.one()
        linhas = await conexao.execute(
            text(
                "SELECT c.relname, pg_get_userbyid(c.relowner),"
                " has_table_privilege(:login, c.oid,"
                "  'SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER')"
                " FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid"
                " WHERE i.inhparent = 'db_change_log'::regclass"
            ),
            {"login": LOGIN_DA_API},
        )
        particoes = {nome: (dono, privilegio) for nome, dono, privilegio in linhas}
    await engine.dispose()

    assert (dono_da_rotina, definer) == ("sgs_owner", True)
    assert particoes == dict.fromkeys(_esperadas(*range(13)), ("sgs_owner", False))


async def test_registro_novo_cai_na_particao_do_mes(banco: BancoDeTeste) -> None:
    """011/R6.5: com as partições da migração, o que o trigger grava hoje vai para a partição
    do mês atual, não para a DEFAULT.
    """
    api = motor(banco.url_api)
    async with api.begin() as conexao:
        await inserir_unidade(conexao, "CAPS José Lucena")
    await api.dispose()
    engine = motor(banco.url_dono)
    async with engine.connect() as conexao:
        registros = await _registros_por_particao(conexao)
    await engine.dispose()

    assert registros == {_nome(0): 1}
