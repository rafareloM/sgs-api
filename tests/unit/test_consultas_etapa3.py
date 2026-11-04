"""Contrato do material SQL da Etapa 03."""

import re
from pathlib import Path

CONSULTAS = Path(__file__).resolve().parents[2] / "consultas_etapa3.sql"


def test_arquivo_contem_quatro_consultas_sql_nomeadas_com_join() -> None:
    conteudo = CONSULTAS.read_text(encoding="utf-8")
    consultas = re.findall(r"(?ms)^-- consulta: ([a-z_]+)\s*\n(.*?)(?=^-- consulta: |\Z)", conteudo)

    assert len(consultas) == 4
    assert len({nome for nome, _ in consultas}) == 4
    assert all(codigo.lstrip().upper().startswith("SELECT") for _, codigo in consultas)
    assert any(re.search(r"\bJOIN\b", codigo, re.IGNORECASE) for _, codigo in consultas)
    assert all(
        re.search(r"\b(unidade_saude|equipamento|alteracao|usuario|perfil)\b", codigo, re.I)
        for _, codigo in consultas
    )
