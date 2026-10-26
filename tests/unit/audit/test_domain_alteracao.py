"""Testes unitários da entidade de domínio de alteração (Alteracao)."""

import pytest

from src.core.errors import DomainValidationError
from src.modules.audit.domain.alteracao import Alteracao


def test_alteracao_valida() -> None:
    alt = Alteracao(
        campo_alterado="Status",
        id_unidade=1,
        id_usuario=2,
        valor_anterior="Ativa",
        valor_novo="Em reforma",
    )
    assert alt.campo_alterado == "Status"
    assert alt.valor_anterior == "Ativa"
    assert alt.valor_novo == "Em reforma"


@pytest.mark.parametrize("campo", ["", "   "])
def test_alteracao_recusa_campo_vazio(campo: str) -> None:
    with pytest.raises(DomainValidationError) as exc:
        Alteracao(
            campo_alterado=campo,
            id_unidade=1,
            id_usuario=2,
            valor_anterior="Ativa",
            valor_novo="Em reforma",
        )
    assert any(err.campo == "campo_alterado" for err in exc.value.errors)


def test_alteracao_recusa_ambos_valores_nulos() -> None:
    with pytest.raises(DomainValidationError) as exc:
        Alteracao(
            campo_alterado="Telefone",
            id_unidade=1,
            id_usuario=2,
            valor_anterior=None,
            valor_novo=None,
        )
    assert any(err.campo == "valores" for err in exc.value.errors)
