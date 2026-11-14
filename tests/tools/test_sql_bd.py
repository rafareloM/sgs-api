"""Arquivo único com o SQL da disciplina: `make sql-bd` (spec 011, T20; R11.3).

O comando roda como o `make` o chama, num processo à parte, sem banco: o DDL vem do modo
offline do Alembic e as consultas, dos `.sql` dos módulos.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from alembic.script import ScriptDirectory

from src.core.db import PROJECT_ROOT, alembic_config

DDL = PROJECT_ROOT / "migrations" / "sql"
CONSULTAS = sorted(PROJECT_ROOT.glob("src/modules/*/infrastructure/sql/*.sql"))


def _instrucao(arquivo: Path) -> str:
    """O texto do arquivo até o `;` final, como o carregador o manda ao banco."""
    texto = arquivo.read_text(encoding="utf-8").rstrip()
    return texto.removesuffix(";").rstrip()


def _ddl_na_ordem_das_migracoes() -> list[Path]:
    """Os `.sql` das migrações: revisões na ordem da cadeia do Alembic, arquivos pelo número."""
    script = ScriptDirectory.from_config(alembic_config())
    revisoes = [r.revision for r in reversed(list(script.walk_revisions()))]
    pastas = sorted((p for p in DDL.iterdir() if p.is_dir()), key=lambda p: revisoes.index(p.name))
    return [arquivo for pasta in pastas for arquivo in sorted(pasta.glob("*.sql"))]


@pytest.fixture(scope="module")
def sql_bd(tmp_path_factory: pytest.TempPathFactory) -> str:
    """Roda `python -m src.tools.sql_bd <saída>` (a receita do `make sql-bd`) sem banco."""
    saida = tmp_path_factory.mktemp("build") / "sql-bd.sql"
    ambiente = {
        nome: valor for nome, valor in os.environ.items() if not nome.startswith("DATABASE")
    }
    ambiente.pop("PYTHONUTF8", None)  # o comando acerta a codificação sozinho, também no Windows
    resultado = subprocess.run(  # noqa: S603 (comando fixo, sem entrada de usuário)
        [sys.executable, "-m", "src.tools.sql_bd", str(saida)],
        cwd=PROJECT_ROOT,
        env=ambiente,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=180,
        check=False,
    )
    assert resultado.returncode == 0, resultado.stderr
    return saida.read_text(encoding="utf-8")


def test_ddl_de_cada_arquivo_sai_com_cabecalho_na_ordem_das_migracoes(sql_bd: str) -> None:
    """011/R11.3: todo o DDL escrito à mão, com o cabeçalho, na ordem de execução."""
    posicoes = []
    for arquivo in _ddl_na_ordem_das_migracoes():
        instrucao = _instrucao(arquivo)
        assert instrucao in sql_bd, arquivo.relative_to(PROJECT_ROOT).as_posix()
        posicoes.append(sql_bd.index(instrucao))

    assert posicoes == sorted(posicoes)


def test_ddl_inclui_as_migracoes_sem_arquivo_e_termina_na_cabeca(sql_bd: str) -> None:
    """011/R11.3: as revisões escritas em Python (0001 a 0003) também entram, antes das outras,
    e o arquivo leva o banco até a cabeça do Alembic.
    """
    cabeca = ScriptDirectory.from_config(alembic_config()).get_current_head()

    assert sql_bd.index("CREATE TABLE audit_log (") < sql_bd.index("CREATE TABLE roles (")
    assert sql_bd.index("CREATE TABLE roles (") < sql_bd.index("CREATE FUNCTION fn_normalize_name")
    versoes = re.findall(r"UPDATE alembic_version SET version_num='([^']+)'", sql_bd)
    assert versoes[-1] == cabeca


def test_consultas_dos_modulos_vem_depois_do_ddl_com_o_caminho(sql_bd: str) -> None:
    """011/R11.3: cada consulta dos módulos, com o cabeçalho, depois de toda a criação, cada uma
    identificada pelo caminho do arquivo e em ordem de módulo e nome.
    """
    fim_do_ddl = sql_bd.index(_instrucao(_ddl_na_ordem_das_migracoes()[-1]))
    posicoes = []
    for arquivo in CONSULTAS:
        caminho = arquivo.relative_to(PROJECT_ROOT).as_posix()
        conteudo = arquivo.read_text(encoding="utf-8").rstrip()
        assert f"-- Arquivo: {caminho}\n{conteudo}" in sql_bd, caminho
        posicoes.append(sql_bd.index(conteudo))

    assert len(CONSULTAS) > 20
    assert fim_do_ddl < min(posicoes)
    assert posicoes == sorted(posicoes)


def test_make_sql_bd_gera_em_build_fora_do_git() -> None:
    """011/R11.3: `make sql-bd` chama o comando com `build/sql-bd.sql`, e `build/` não vai ao
    Git.
    """
    makefile = (PROJECT_ROOT / "Makefile").read_text(encoding="utf-8")
    gitignore = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()

    receita = re.search(r"^sql-bd:.*\n((?:\t.*\n)+)", makefile, re.MULTILINE)
    assert receita is not None
    assert "python -m src.tools.sql_bd build/sql-bd.sql" in receita.group(1)
    assert re.search(r"^\.PHONY:.*\bsql-bd\b", makefile, re.MULTILINE)
    assert "build/" in gitignore
