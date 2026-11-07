"""Carregador do DDL escrito à mão das migrações (spec 011, R11.1 e R11.2; ADR-0009)."""

import io
import os
import subprocess
import sys
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory

from migrations import sql_loader
from src.core.db import PROJECT_ROOT, alembic_config

REVISAO = "9999"
ARQUIVO = "01_exemplo.sql"


class DdlOffline:
    """Grava um `.sql` de uma revisão de teste e o executa como no `alembic upgrade --sql`."""

    def __init__(self, raiz: Path) -> None:
        self.raiz = raiz

    def executar(self, conteudo: str) -> str:
        pasta = self.raiz / REVISAO
        pasta.mkdir(exist_ok=True)
        (pasta / ARQUIVO).write_text(conteudo, encoding="utf-8")
        saida = io.StringIO()
        contexto = MigrationContext.configure(
            dialect_name="postgresql",
            dialect_opts={"paramstyle": "named"},
            opts={"as_sql": True, "output_buffer": saida, "literal_binds": True},
        )
        with Operations.context(contexto):
            sql_loader.executar_sql(REVISAO, ARQUIVO)
        return saida.getvalue()


@pytest.fixture
def ddl_offline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> DdlOffline:
    monkeypatch.setattr(sql_loader, "DIRETORIO_SQL", tmp_path)
    return DdlOffline(tmp_path)


def test_hh24mi_atribuicao_e_dois_pontos_do_cabecalho_passam_intactos(
    ddl_offline: DdlOffline,
) -> None:
    """011/R11.2: o SQL executado é o do arquivo; nenhum `:` vira parâmetro do `text()`."""
    conteudo = (
        "-- Uso: o repositório chama SELECT fn_hora_formatada(:id).\n"
        "CREATE FUNCTION fn_hora_formatada() RETURNS text LANGUAGE plpgsql AS $$\n"
        "DECLARE\n"
        "    v_hora text;\n"
        "BEGIN\n"
        "    v_hora := to_char(now(), 'HH24:MI');\n"
        "    RETURN v_hora;\n"
        "END\n"
        "$$;\n"
    )

    saida = ddl_offline.executar(conteudo)

    assert "-- Uso: o repositório chama SELECT fn_hora_formatada(:id).\n" in saida
    assert "    v_hora := to_char(now(), 'HH24:MI');\n" in saida
    assert "END\n$$;" in saida


def test_arquivo_com_duas_instrucoes_e_recusado(ddl_offline: DdlOffline) -> None:
    """011/R11.1: uma instrução por arquivo; o asyncpg não prepara duas no mesmo texto."""
    conteudo = (
        "-- Objetivo: duas tabelas no mesmo arquivo, o que não pode.\n"
        "CREATE TABLE exemplo_a (id integer);\n"
        "CREATE TABLE exemplo_b (id integer);\n"
    )

    with pytest.raises(sql_loader.ArquivoSqlError, match=r"9999/01_exemplo\.sql.*mais de uma"):
        ddl_offline.executar(conteudo)


def test_ponto_e_virgula_em_comentario_string_e_identificador_nao_encerra_instrucao(
    ddl_offline: DdlOffline,
) -> None:
    """011/R11.1: só o `;` fora de comentário, string e identificador conta como fim."""
    instrucao = (
        "SELECT 'texto; com '' aspas;' AS \"coluna;estranha\", E'barra \\' ; ainda texto' AS e"
    )
    conteudo = (
        "-- Objetivo: o ; deste comentário não encerra a instrução.\n"
        "/* Justificativa: nem este; /* nem o aninhado; */ ainda comentário; */\n"
        f"{instrucao};\n"
        "-- Fim do arquivo; comentário depois do ponto e vírgula.\n"
    )

    saida = ddl_offline.executar(conteudo)

    assert f"\n{instrucao};" in saida


@pytest.mark.parametrize(
    ("conteudo", "motivo"),
    [
        ("-- Objetivo: só o cabeçalho, sem instrução.\n", "nenhuma instrução"),
        ("CREATE FUNCTION fn_sem_fim() RETURNS void LANGUAGE sql AS $$ SELECT 1", "sem fechamento"),
        (
            "/* Objetivo: comentário que não fecha\nCREATE TABLE exemplo (id integer)",
            "sem fechamento",
        ),
    ],
    ids=["sem_instrucao", "corpo_sem_fechamento", "comentario_sem_fechamento"],
)
def test_arquivo_sem_exatamente_uma_instrucao_completa_e_recusado(
    ddl_offline: DdlOffline, conteudo: str, motivo: str
) -> None:
    """011/R11.1: o arquivo tem exatamente uma instrução, inteira."""
    with pytest.raises(sql_loader.ArquivoSqlError, match=motivo):
        ddl_offline.executar(conteudo)


def test_upgrade_head_offline_imprime_o_ddl_sem_banco(tmp_path: Path) -> None:
    """011/R11.2: `alembic upgrade head --sql` gera o DDL sem conectar nem ler a configuração."""
    ambiente = {
        nome: valor for nome, valor in os.environ.items() if not nome.startswith("DATABASE")
    }
    ambiente["PYTHONUTF8"] = "1"  # no Windows, a saída do processo filho sairia em cp1252
    cabeca = ScriptDirectory.from_config(alembic_config()).get_current_head()

    resultado = subprocess.run(  # noqa: S603 (comando fixo, sem entrada de usuário)
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            str(PROJECT_ROOT / "alembic.ini"),
            "upgrade",
            "head",
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
    assert "CREATE TABLE audit_log (" in resultado.stdout
    ultima_versao = [
        linha for linha in resultado.stdout.splitlines() if "UPDATE alembic_version" in linha
    ][-1]
    assert f"version_num='{cabeca}' WHERE" in ultima_versao
