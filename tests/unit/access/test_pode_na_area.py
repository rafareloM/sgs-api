"""`pode_na_area()`: o que só se altera com escopo global ou de área técnica (006/T5).

Os campos estruturais da unidade (distrito, tipo e CNES) exigem `unidade:update` com escopo
global ou na área técnica da unidade; distrito e unidade não bastam (006/R3.4).
"""

from uuid import UUID

import pytest

from src.modules.access.domain.authorization import (
    Area,
    Distrito,
    Escopo,
    Global,
    Unidade,
    pode_na_area,
)

SAUDE_MENTAL = 1
UNIDADE = UUID("01900000-0000-7000-8000-000000000001")


@pytest.mark.parametrize(
    ("escopos", "esperado"),
    [
        ((Global(),), True),
        ((Area(SAUDE_MENTAL),), True),
        ((Area(2),), False),
        ((Distrito(1),), False),
        ((Unidade(UNIDADE),), False),
        ((Distrito(1), Unidade(UNIDADE), Area(SAUDE_MENTAL)), True),
        ((), False),
    ],
    ids=["global", "area-da-unidade", "outra-area", "distrito", "unidade", "varios", "nenhum"],
)
def test_so_global_ou_a_area_da_unidade_altera_campo_estrutural(
    escopos: tuple[Escopo, ...], esperado: bool
) -> None:
    """006/R3.4."""
    assert pode_na_area({"unidade:update": escopos}, "unidade:update", SAUDE_MENTAL) is esperado


def test_outra_permissao_nao_conta() -> None:
    """Deny by default: o escopo global de outra permissão não dá esta."""
    assert pode_na_area({"unidade:read": (Global(),)}, "unidade:update", SAUDE_MENTAL) is False
