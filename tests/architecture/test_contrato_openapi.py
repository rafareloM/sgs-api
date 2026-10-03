"""O contrato versionado é o que o código gera (spec 001, R7.1; AGENTS.md, regra 8)."""

from pathlib import Path

from src.tools.export_openapi import build_contract

CONTRATO = Path(__file__).resolve().parents[2] / "contracts" / "openapi.yaml"


def test_contrato_openapi_versionado_esta_atualizado() -> None:
    """001/R7.1"""
    assert CONTRATO.read_text(encoding="utf-8") == build_contract(), (
        "contracts/openapi.yaml divergiu do código: rode `make openapi` e versione o resultado."
    )
