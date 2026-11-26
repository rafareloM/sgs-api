"""O `.gitignore` não esconde código de `src/` nem de `tests/`.

Em 25/11/2026, a linha `reports/`, pensada para a saída de junit e cobertura na raiz, casava também
com `src/modules/reports/`. Os arquivos novos do módulo não apareciam no `git status`, e o ruff, que
respeita o `.gitignore`, deixava o módulo sem lint: o `make check` passava sem conferi-lo. Sem git,
o teste é pulado.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
GIT = shutil.which("git")


def _git_ls_files(*opcoes: str) -> list[str]:
    if GIT is None or not (RAIZ / ".git").exists():
        pytest.skip("sem git: o .gitignore não foi conferido")
    resultado = subprocess.run(  # noqa: S603 - comando fixo, sem entrada externa
        [GIT, "ls-files", *opcoes, "--exclude-standard", "--", *_CAMINHOS[opcoes[0]]],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
        cwd=RAIZ,
    )
    return resultado.stdout.splitlines()


_CAMINHOS = {
    "--cached": ("src", "tests"),
    # No pathspec do git, `*` atravessa pastas: vale para qualquer .py abaixo de src/ e tests/.
    "--others": ("src/*.py", "tests/*.py"),
}


def test_nenhum_arquivo_versionado_de_src_e_tests_casa_com_o_gitignore() -> None:
    escondidos = _git_ls_files("--cached", "--ignored")
    assert escondidos == [], f"o .gitignore casa com arquivos versionados: {escondidos[:10]}"


def test_nenhum_python_novo_de_src_e_tests_fica_escondido_pelo_gitignore() -> None:
    escondidos = _git_ls_files("--others", "--ignored")
    assert escondidos == [], f"o .gitignore esconde código novo: {escondidos[:10]}"
