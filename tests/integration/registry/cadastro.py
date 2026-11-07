"""Linhas do cadastro inseridas direto no banco, para os testes do esquema da 0006.

Distrito, tipo de unidade, tipo de equipamento e tipo de serviço são indicados pelo código das
referências semeadas pela migração, nunca pelo id que o banco gerou.
"""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from src.core.ids import uuid7


async def inserir_unidade(
    conexao: AsyncConnection,
    nome: str,
    *,
    distrito: str = "DS-I",
    tipo: str = "CAPS_II",
    cnes: str | None = None,
) -> UUID:
    """Unidade ativa só com os campos obrigatórios (006/R1.2), mais o CNES se informado."""
    unidade = uuid7()
    await conexao.execute(
        text(
            "INSERT INTO health_units"
            " (id, name, cnes, district_id, unit_type_id, cep, address, status)"
            " VALUES (:id, :nome, :cnes,"
            " (SELECT id FROM districts WHERE code = :distrito),"
            " (SELECT id FROM unit_types WHERE code = :tipo),"
            " '50010100', 'Rua do Sol, 150', 'ativa')"
        ),
        {"id": unidade, "nome": nome, "cnes": cnes, "distrito": distrito, "tipo": tipo},
    )
    return unidade


async def inserir_equipamento(
    conexao: AsyncConnection,
    unidade: UUID | None,
    *,
    nome: str = "Maternidade Bandeira Filho",
    tipo: str = "MATERNIDADE",
) -> UUID:
    """Equipamento de uma unidade, ou sem unidade (006/R5.2) quando `unidade` é `None`."""
    equipamento = uuid7()
    await conexao.execute(
        text(
            "INSERT INTO equipments (id, unit_id, name, equipment_type_code, status)"
            " VALUES (:id, :unidade, :nome, :tipo, 'ativo')"
        ),
        {"id": equipamento, "unidade": unidade, "nome": nome, "tipo": tipo},
    )
    return equipamento


async def inserir_servico(
    conexao: AsyncConnection,
    unidade: UUID | None,
    *,
    equipamento: UUID | None = None,
    nome: str = "Farmácia do CAPS",
    tipo: str = "FARMACIA",
    no_cnes: bool = False,
) -> UUID:
    """Serviço de uma unidade (e, se informado, de um equipamento), ou solto (006/R6.2)."""
    servico = uuid7()
    await conexao.execute(
        text(
            "INSERT INTO services"
            " (id, service_type_id, unit_id, equipment_id, name, in_cnes, status)"
            " VALUES (:id, (SELECT id FROM service_types WHERE code = :tipo),"
            " :unidade, :equipamento, :nome, :no_cnes, 'ativo')"
        ),
        {
            "id": servico,
            "tipo": tipo,
            "unidade": unidade,
            "equipamento": equipamento,
            "nome": nome,
            "no_cnes": no_cnes,
        },
    )
    return servico
