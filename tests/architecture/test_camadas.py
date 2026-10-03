"""Regras de dependência entre camadas (steering/structure.md), verificadas pelo import-linter."""

import tomllib
from pathlib import Path

from importlinter.cli import EXIT_STATUS_SUCCESS, lint_imports

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"

CONTRATOS_OBRIGATORIOS = {
    "dominio-puro",
    "dominios-independentes",
    "camadas-dos-modulos",
    "aplicacao-sem-frameworks",
    "infraestrutura-protegida",
    "infraestrutura-isolada",
}


def _contratos_configurados() -> set[str]:
    config = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    contratos = config["tool"]["importlinter"].get("contracts", [])
    return {str(contrato["id"]) for contrato in contratos}


def test_contratos_de_camadas_estao_configurados() -> None:
    """001/R7.1"""
    ausentes = CONTRATOS_OBRIGATORIOS - _contratos_configurados()
    assert not ausentes, f"Contratos ausentes no pyproject.toml: {sorted(ausentes)}"


def test_codigo_respeita_os_contratos_de_camadas() -> None:
    """001/R7.1"""
    resultado = lint_imports(config_filename=str(PYPROJECT), no_cache=True, no_logo=True)
    assert resultado == EXIT_STATUS_SUCCESS
