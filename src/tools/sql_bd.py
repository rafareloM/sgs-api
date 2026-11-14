"""Gera o arquivo único com o SQL da disciplina de Banco de Dados (`make sql-bd`; spec 011, R11.3).

    uv run python -m src.tools.sql_bd build/sql-bd.sql

1. Criação: o DDL de `alembic upgrade head --sql` (modo offline, sem banco), na ordem das
   migrações, com os cabeçalhos dos `.sql` de `migrations/sql/` carregados por elas.
2. Consultas: cada `src/modules/<módulo>/infrastructure/sql/<nome>.sql`, por módulo e nome,
   precedido do caminho do arquivo.

O texto é o mesmo dos arquivos que a aplicação executa (R11.2). O arquivo é gravado em UTF-8
com LF; o Alembic roda num processo à parte com `PYTHONUTF8=1`, porque no Windows a saída dele
sairia em cp1252 e estragaria os acentos dos cabeçalhos.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

from src.core.db import PROJECT_ROOT

_CONSULTAS = "src/modules/*/infrastructure/sql/*.sql"

_ABERTURA = """\
-- SQL da disciplina de Banco de Dados · sgs-api (spec 011, R11.3)
-- Gerado por `make sql-bd`; não edite: a fonte são os arquivos citados abaixo (ADR-0009).
-- Parte 1: criação, na ordem das migrações (`alembic upgrade head --sql`).
-- Parte 2: consultas da aplicação, com parâmetros nomeados (`:nome`) preenchidos pela API.
"""


def ddl_offline() -> str:
    """O DDL de todas as migrações, como o `alembic upgrade head --sql` o imprime."""
    ambiente = os.environ | {"PYTHONUTF8": "1"}
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
        cwd=PROJECT_ROOT,
        env=ambiente,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if resultado.returncode != 0:
        raise RuntimeError(f"alembic upgrade head --sql falhou:\n{resultado.stderr}")
    return resultado.stdout


def consultas() -> str:
    """As consultas dos módulos, cada uma depois de uma linha com o caminho do arquivo."""
    blocos = []
    for arquivo in sorted(PROJECT_ROOT.glob(_CONSULTAS)):
        caminho = arquivo.relative_to(PROJECT_ROOT).as_posix()
        blocos.append(f"-- Arquivo: {caminho}\n{arquivo.read_text(encoding='utf-8').rstrip()}\n")
    return "\n".join(blocos)


def gerar() -> str:
    return (
        f"{_ABERTURA}\n"
        "-- ===== Parte 1: criação =====\n\n"
        f"{ddl_offline().rstrip()}\n\n"
        "-- ===== Parte 2: consultas =====\n\n"
        f"{consultas()}"
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("saida", type=Path, help="arquivo a gerar, por exemplo build/sql-bd.sql")
    args = parser.parse_args(argv)
    args.saida.parent.mkdir(parents=True, exist_ok=True)
    args.saida.write_bytes(gerar().encode("utf-8"))
    print(f"SQL da disciplina gravado em {args.saida}")  # noqa: T201


if __name__ == "__main__":
    main()
