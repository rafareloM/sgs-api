"""Ferramenta do `security.toml` do SeaweedFS de laboratório (005/T8)."""

import tomllib
from pathlib import Path

import pytest

from src.tools import s3_sse_key


def test_gera_a_secao_s3_sse_com_chave_nova(tmp_path: Path) -> None:
    """005/R2.8, R6.1 (a SSE do laboratório precisa de chave)"""
    saida = tmp_path / "secrets" / "s3-security.toml"

    assert s3_sse_key.main(["--output", str(saida)]) == 0

    chave = tomllib.loads(saida.read_text(encoding="utf-8"))["s3"]["sse"]["key"]
    outra = tomllib.loads(s3_sse_key.novo_security_toml())["s3"]["sse"]["key"]
    assert len(chave) == 64
    assert chave != outra


def test_nao_sobrescreve_a_chave_existente(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """005/R2.8 (uma chave nova deixaria ilegível o que já foi cifrado)"""
    saida = tmp_path / "s3-security.toml"
    saida.write_text("antigo", encoding="utf-8")

    assert s3_sse_key.main(["--output", str(saida)]) == 1
    assert saida.read_text(encoding="utf-8") == "antigo"
    assert "já existe" in capsys.readouterr().err
