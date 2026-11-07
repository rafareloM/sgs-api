"""Comando `sgs-admin banco particoes [--meses N]` (011/T8, R6.8).

O comando lê a configuração do ambiente, como em produção: cada teste define as variáveis do
banco de teste e chama o `main` numa thread (ele abre o próprio laço de eventos). O banco é lido
pelo dono, à parte.
"""

import asyncio
import os
import shutil
import subprocess
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from sqlalchemy import text

from src.tools.sgs_admin import main
from tests.factories import make_jwt_private_keys
from tests.integration.postgres import BancoDeTeste, motor


def _nome(deslocamento: int) -> str:
    """Partição do log do mês `deslocamento` meses depois do atual, em UTC."""
    hoje = datetime.now(UTC).date()
    indice = hoje.year * 12 + hoje.month - 1 + deslocamento
    mes = date(indice // 12, indice % 12 + 1, 1)
    return f"db_change_log_y{mes.year:04d}m{mes.month:02d}"


async def _particoes(banco: BancoDeTeste) -> set[str]:
    engine = motor(banco.url_dono)
    async with engine.connect() as conexao:
        linhas = await conexao.execute(
            text(
                "SELECT c.relname FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid"
                " WHERE i.inhparent = 'db_change_log'::regclass AND c.relname <> :padrao"
            ),
            {"padrao": "db_change_log_default"},
        )
        nomes = set(linhas.scalars())
    await engine.dispose()
    return nomes


@pytest.fixture
def ambiente(monkeypatch: pytest.MonkeyPatch, banco: BancoDeTeste) -> BancoDeTeste:
    """Variáveis de ambiente da configuração (`Settings`) apontando para o banco do teste."""
    for nome in ("JWT_PRIVATE_KEYS_FILE", "DATABASE_SSL_ROOT_CERT"):
        monkeypatch.delenv(nome, raising=False)
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", banco.url_api)
    monkeypatch.setenv("DATABASE_MIGRATION_URL", banco.url_dono)
    monkeypatch.setenv("DATABASE_SSL_MODE", "disable")
    monkeypatch.setenv("JWT_PRIVATE_KEYS", make_jwt_private_keys())
    return banco


async def test_comando_cria_as_particoes_ate_os_meses_pedidos(
    ambiente: BancoDeTeste, capsys: pytest.CaptureFixture[str]
) -> None:
    """011/R6.8: o comando executa o procedimento com o horizonte pedido e mostra o que criou."""
    codigo = await asyncio.to_thread(main, ["banco", "particoes", "--meses", "14"])

    saida = capsys.readouterr()
    assert codigo == 0, saida.err
    assert await _particoes(ambiente) == {_nome(d) for d in range(15)}
    assert f"partição {_nome(13)} criada" in saida.out
    assert f"partição {_nome(14)} criada" in saida.out
    assert f"partição {_nome(12)} criada" not in saida.out


async def test_sem_meses_garante_doze_meses_a_frente(
    ambiente: BancoDeTeste, capsys: pytest.CaptureFixture[str]
) -> None:
    """011/R6.8 e R6.7: sem `--meses`, o horizonte é o da migração, 12 meses à frente."""
    engine = motor(ambiente.url_dono)
    async with engine.begin() as conexao:
        await conexao.execute(text(f"DROP TABLE {_nome(6)}"))
    await engine.dispose()

    codigo = await asyncio.to_thread(main, ["banco", "particoes"])

    saida = capsys.readouterr()
    assert codigo == 0, saida.err
    assert await _particoes(ambiente) == {_nome(d) for d in range(13)}
    assert f"partição {_nome(6)} criada" in saida.out


async def test_mes_pulado_sai_como_aviso(
    ambiente: BancoDeTeste, capsys: pytest.CaptureFixture[str]
) -> None:
    """011/R6.6: o aviso do procedimento sobre um mês com registros na DEFAULT chega a quem
    roda o comando, na saída de erro; o comando segue e termina bem.
    """
    engine = motor(ambiente.url_dono)
    async with engine.begin() as conexao:
        await conexao.execute(text(f"DROP TABLE {_nome(1)}"))
        await conexao.execute(
            text(
                "INSERT INTO db_change_log (occurred_at, table_name, operation, row_id,"
                " changed_columns, db_user, via_api, txid)"
                " VALUES (date_trunc('month', now()) + interval '1 month 3 days', 'services',"
                " 'DELETE', gen_random_uuid(), '{}', current_user, false, txid_current())"
            )
        )
    await engine.dispose()

    codigo = await asyncio.to_thread(main, ["banco", "particoes"])

    saida = capsys.readouterr()
    assert codigo == 0, saida.err
    assert await _particoes(ambiente) == {_nome(d) for d in range(13) if d != 1}
    assert "aviso: db_change_log: o mês " in saida.err
    assert f"a partição {_nome(1)} não foi criada" in saida.err


async def test_sem_url_do_dono_usa_a_da_api_e_sai_com_erro(
    ambiente: BancoDeTeste, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """011/R6.8 e R10.1: sem DATABASE_MIGRATION_URL, o comando conecta com DATABASE_URL, como as
    migrações; o login da API não executa o procedimento, e o comando sai com erro, sem
    traceback nem a URL, e sem criar nada.
    """
    monkeypatch.delenv("DATABASE_MIGRATION_URL")
    engine = motor(ambiente.url_dono)
    async with engine.begin() as conexao:
        await conexao.execute(text(f"DROP TABLE {_nome(7)}"))
    await engine.dispose()

    codigo = await asyncio.to_thread(main, ["banco", "particoes"])

    saida = capsys.readouterr()
    assert codigo == 1
    assert saida.err == (
        "sgs-admin: o usuário de banco não pode executar sp_ensure_monthly_partitions;"
        " defina DATABASE_MIGRATION_URL com o dono do banco\n"
    )
    assert saida.out == ""
    assert await _particoes(ambiente) == {_nome(d) for d in range(13) if d != 7}


@pytest.mark.parametrize("meses", ["-1", "doze"])
def test_meses_invalidos_sao_recusados(meses: str, capsys: pytest.CaptureFixture[str]) -> None:
    """011/R6.8: `--meses` aceita só inteiro de 0 para cima; o resto para antes de conectar."""
    with pytest.raises(SystemExit) as saida:
        main(["banco", "particoes", "--meses", meses])

    assert saida.value.code == 2
    assert "--meses" in capsys.readouterr().err


async def test_ponto_de_entrada_sgs_admin_esta_instalado(ambiente: BancoDeTeste) -> None:
    """011/R6.8: `sgs-admin` é um comando instalado com o projeto (`[project.scripts]`), o que
    o administrador roda no container da API.
    """
    executavel = shutil.which("sgs-admin", path=str(Path(sys.executable).parent))
    assert executavel is not None
    # O ambiente do teste (fixture `ambiente`) já tem as variáveis do banco de teste.
    filho = os.environ | {"PYTHONUTF8": "1"}  # no Windows, a saída sairia em cp1252

    resultado = await asyncio.to_thread(
        subprocess.run,
        [executavel, "banco", "particoes", "--meses", "13"],
        env=filho,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )

    assert resultado.returncode == 0, resultado.stderr
    assert f"partição {_nome(13)} criada" in resultado.stdout
    assert await _particoes(ambiente) == {_nome(d) for d in range(14)}
