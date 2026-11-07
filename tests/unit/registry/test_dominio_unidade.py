"""Domínio da unidade: normalização de nome, `diff` e campos estruturais (006/T2).

Os resultados esperados da normalização foram conferidos contra a `fn_normalize_name` do design
da 011 rodando num `postgres:17` (locale `en_US.utf8`), para os dois lados não divergirem.
"""

import pytest

from src.modules.registry.domain.unidade import (
    Mudanca,
    campos_estruturais_alterados,
    diff,
    normalizar_nome,
)


@pytest.mark.parametrize(
    ("nome", "esperado"),
    [
        ("Espaço  Azul", "espaco azul"),
        ("  USF Alto do Mandu  ", "usf alto do mandu"),
        ("Policlínica Gouveia de Barros", "policlinica gouveia de barros"),
        ("SÃO JOÃO", "sao joao"),
        ("ÁÉÍÓÚ àèìòù ÂÊÔ ãõ ç Ç ü", "aeiou aeiou aeo ao c c u"),
    ],
)
def test_normalizar_nome_tira_acento_caixa_e_espacos_extras(nome: str, esperado: str) -> None:
    """006/R1.4 (sem acento, caixa e espaços extras; regra de 011/R5.1)"""
    assert normalizar_nome(nome) == esperado


@pytest.mark.parametrize(
    ("nome", "esperado"),
    [
        # Tab, quebra de linha e espaços Unicode do `\s` do Postgres viram um espaço só.
        ("Centro\t de\nSaúde", "centro de saude"),
        ("Unidade\u2003\u2003Leste", "unidade leste"),
        # O espaço não separável não é `\s` no Postgres nem sai no `unaccent`: fica.
        ("Hospital\u00a0da  Mulher", "hospital\u00a0da mulher"),
        # O `btrim` vai por fora: tab e quebra de linha nas pontas também saem (decisão do
        # Rafael, 07/11/2026; 011/R5.1).
        ("UPA  Ibura\t", "upa ibura"),
        ("\n CAPS Esperança \t", "caps esperanca"),
        ("Nº 1º Distrito", "nº 1º distrito"),
    ],
)
def test_normalizar_nome_trata_espacos_e_simbolos_como_a_funcao_do_banco(
    nome: str, esperado: str
) -> None:
    """006/R1.4, 011/R5.2 (o mesmo texto normaliza igual no domínio e na `fn_normalize_name`)"""
    assert normalizar_nome(nome) == esperado


def test_diff_lista_de_e_para_dos_campos_que_mudaram() -> None:
    """006/R3.5 (lista de campos `{campo, de, para}` para a auditoria)"""
    antes = {"name": "USF Alto", "phone": "8133330000", "cnes": None, "status": "ativa"}
    depois = {"name": "USF ALTO", "phone": "8133330000", "cnes": "1234567"}

    assert diff(antes, depois) == [
        Mudanca(campo="name", de="USF Alto", para="USF ALTO"),
        Mudanca(campo="cnes", de=None, para="1234567"),
    ]


def test_diff_sem_valor_novo_nao_gera_mudanca() -> None:
    """006/R3.6 (nada mudou: sem registro de auditoria)"""
    antes = {
        "name": "USF Alto",
        "phone": "8133330000",
        "opening_hours": {"seg": ["07:00", "17:00"]},
    }
    depois = {"phone": "8133330000", "opening_hours": {"seg": ["07:00", "17:00"]}}

    assert diff(antes, depois) == []


def test_campos_estruturais_alterados_aponta_distrito_tipo_e_cnes() -> None:
    """006/R3.4 (distrito, tipo e CNES só com escopo global ou de área)"""
    antes = {"name": "USF Alto", "district_id": 3, "unit_type_id": 1, "cnes": None}
    depois = {"name": "USF Alto do Mandu", "district_id": 5, "unit_type_id": 2, "cnes": "1234567"}

    assert campos_estruturais_alterados(diff(antes, depois)) == [
        "district_id",
        "unit_type_id",
        "cnes",
    ]


def test_campos_estruturais_nao_alterados_nao_sao_apontados() -> None:
    """006/R3.4 (enviar o distrito, o tipo ou o CNES sem mudar o valor não é alterá-los)"""
    antes = {"name": "USF Alto", "district_id": 3, "unit_type_id": 1, "cnes": "1234567"}
    depois = {"name": "USF Alto do Mandu", "district_id": 3, "unit_type_id": 1, "cnes": "1234567"}

    assert campos_estruturais_alterados(diff(antes, depois)) == []
