"""Situação cadastral da unidade calculada no banco: `fn_registration_status` (011/T3).

Pelo login da API, que é quem chama a função (inventário e relatórios, 011/T4 e T13).
"""

import pytest
from sqlalchemy import text

from tests.integration.postgres import BancoDeTeste, motor
from tests.integration.registry.cadastro import inserir_unidade

# (status, pendências, CNES) → situação, pela precedência de 011/R5.3: inativa, com_pendencias,
# sem_cnes, regular. Cada caso traz também as condições de menor precedência, para provar a ordem.
CASOS = {
    "inativa-vence-pendencias-e-falta-de-cnes": ("inativa", 2, None, "inativa"),
    "inativa-regular-no-resto": ("inativa", 0, "2345678", "inativa"),
    "pendencias-vencem-falta-de-cnes": ("ativa", 2, None, "com_pendencias"),
    "pendencias-com-cnes": ("ativa", 1, "2345678", "com_pendencias"),
    "sem-cnes": ("ativa", 0, None, "sem_cnes"),
    "regular": ("ativa", 0, "2345678", "regular"),
    "em-implantacao-sem-pendencia-com-cnes-e-regular": ("em_implantacao", 0, "2345678", "regular"),
}


@pytest.mark.parametrize(("status", "pendencias", "cnes", "esperada"), CASOS.values(), ids=CASOS)
async def test_situacao_cadastral_segue_a_precedencia_aprovada(
    banco: BancoDeTeste, status: str, pendencias: int, cnes: str | None, esperada: str
) -> None:
    """011/R5.3: inativa > com_pendencias > sem_cnes > regular (decisão U6 do Rafael)."""
    engine = motor(banco.url_api)
    async with engine.begin() as conexao:
        unidade = await inserir_unidade(conexao, "CAPS Esperança", cnes=cnes)
        await conexao.execute(
            text(
                "UPDATE health_units SET status = :status, pending_issues = :pendencias"
                " WHERE id = :id"
            ),
            {"status": status, "pendencias": pendencias, "id": unidade},
        )
        situacao = await conexao.scalar(
            text("SELECT fn_registration_status(u) FROM health_units u WHERE u.id = :id"),
            {"id": unidade},
        )
    await engine.dispose()

    assert situacao == esperada
