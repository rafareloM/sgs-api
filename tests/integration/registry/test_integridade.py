"""Integridade referencial do cadastro, garantida pelas FKs da 0006 (011/T2, Etapa 02).

Tudo pelo login da API: as regras valem para a aplicação, não só para o dono do banco.
"""

from collections.abc import Awaitable, Callable
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from tests.integration.postgres import BancoDeTeste, motor
from tests.integration.registry.cadastro import (
    inserir_equipamento,
    inserir_servico,
    inserir_unidade,
)

VIOLA_FK = "23503"  # SQLSTATE foreign_key_violation


async def test_remover_equipamento_mantem_os_servicos_na_unidade(banco: BancoDeTeste) -> None:
    """011/R9.1: o serviço do equipamento removido fica, desligado dele e ainda na unidade."""
    engine = motor(banco.url_api)
    async with engine.begin() as conexao:
        unidade = await inserir_unidade(conexao, "Policlínica Lessa de Andrade", tipo="POLICLINICA")
        maternidade = await inserir_equipamento(conexao, unidade)
        servico = await inserir_servico(
            conexao, unidade, equipamento=maternidade, nome="Sala de Vacina da Maternidade"
        )

    async with engine.begin() as conexao:
        await conexao.execute(text("DELETE FROM equipments WHERE id = :id"), {"id": maternidade})
        linha = await conexao.execute(
            text("SELECT unit_id, equipment_id FROM services WHERE id = :id"), {"id": servico}
        )
        unidade_do_servico, equipamento_do_servico = linha.one()
    await engine.dispose()

    assert (unidade_do_servico, equipamento_do_servico) == (unidade, None)


VINCULOS: dict[str, Callable[[AsyncConnection, UUID], Awaitable[UUID]]] = {
    "equipamento": inserir_equipamento,
    "servico": inserir_servico,
}


@pytest.mark.parametrize("vinculo", VINCULOS.values(), ids=VINCULOS.keys())
async def test_unidade_com_vinculos_nao_e_apagada(
    banco: BancoDeTeste, vinculo: Callable[[AsyncConnection, UUID], Awaitable[UUID]]
) -> None:
    """011/R9.3: equipamento ou serviço vinculado impede apagar a unidade (ON DELETE RESTRICT)."""
    engine = motor(banco.url_api)
    async with engine.begin() as conexao:
        unidade = await inserir_unidade(conexao, "CAPS David Capistrano")
        await vinculo(conexao, unidade)

    with pytest.raises(IntegrityError) as erro:
        async with engine.begin() as conexao:
            await conexao.execute(text("DELETE FROM health_units WHERE id = :id"), {"id": unidade})
    async with engine.connect() as conexao:
        restantes = await conexao.scalar(
            text("SELECT count(*) FROM health_units WHERE id = :id"), {"id": unidade}
        )
    await engine.dispose()

    assert getattr(erro.value.orig, "sqlstate", None) == VIOLA_FK
    assert restantes == 1


async def test_correcao_do_codigo_do_tipo_chega_aos_equipamentos(banco: BancoDeTeste) -> None:
    """011/R9.2 (parte do banco; a rota e a auditoria são da 011/T18): ON UPDATE CASCADE."""
    engine = motor(banco.url_api)
    async with engine.begin() as conexao:
        unidade = await inserir_unidade(conexao, "Policlínica Arnaldo Marques", tipo="POLICLINICA")
        equipamento = await inserir_equipamento(conexao, unidade, tipo="MATERNIDADE")
        uti_movel = await inserir_equipamento(conexao, None, nome="UTI móvel 01", tipo="UTI_MOVEL")

    async with engine.begin() as conexao:
        await conexao.execute(
            text(
                "UPDATE equipment_types SET code = 'MATERNIDADE_MUNICIPAL'"
                " WHERE code = 'MATERNIDADE'"
            )
        )
        linhas = await conexao.execute(text("SELECT id, equipment_type_code FROM equipments"))
        codigos: dict[UUID, str] = {id_: str(codigo) for id_, codigo in linhas}
    await engine.dispose()

    assert codigos == {equipamento: "MATERNIDADE_MUNICIPAL", uti_movel: "UTI_MOVEL"}
