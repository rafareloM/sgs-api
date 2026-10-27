"""Casos de uso de escrita para o CRUD mínimo da Etapa 03."""

from collections.abc import Mapping
from typing import Any

from src.core.errors import NotFound
from src.modules.registry.application.ports import RegistryStore
from src.modules.registry.domain.equipamento import Equipamento
from src.modules.registry.domain.unidade import STATUS_UNIDADE_VALIDOS, UnidadeSaude


async def criar_unidade(
    store: RegistryStore, dados: Mapping[str, Any], autor_id: int
) -> dict[str, Any]:
    nome = " ".join(str(dados["nome"]).split())
    UnidadeSaude(
        codigo_cnes=dados["codigocnes"],
        nome=nome,
        tipo=str(dados["tipo"]),
        endereco=str(dados["endereco"]),
        cep=str(dados["cep"]),
        distrito_sanitario=str(dados["distritosanitario"]),
        telefone=str(dados["telefone"]) if dados["telefone"] is not None else None,
        status=str(dados["status"]),
    )
    valores = dict(dados)
    valores["nome"] = nome
    valores["cnes_pendente"] = dados["codigocnes"] is None
    return await store.create_unidade(valores, autor_id)


async def atualizar_status_unidade(
    store: RegistryStore,
    *,
    unidade_id: int,
    status: str,
    versao: int,
    autor_id: int,
    motivo: str | None,
) -> dict[str, Any]:
    if status not in STATUS_UNIDADE_VALIDOS:
        raise ValueError("Status de unidade inválido.")
    unidade = await store.update_status(unidade_id, status, versao, autor_id, motivo)
    if unidade is None:
        raise NotFound("Unidade não encontrada.")
    return unidade


async def criar_equipamento(
    store: RegistryStore,
    *,
    unidade_id: int | None,
    dados: Mapping[str, Any],
) -> dict[str, Any]:
    Equipamento(
        nome=str(dados["nome"]),
        tipo=str(dados["tipo"]),
        quantidade=int(dados["quantidade"]),
        id_unidade=unidade_id,
    )
    return await store.create_equipamento(unidade_id, dados)


async def atualizar_equipamento(
    store: RegistryStore,
    *,
    equipamento_id: int,
    dados: Mapping[str, Any],
) -> dict[str, Any]:
    anterior = await store.get_equipamento(equipamento_id)
    if anterior is None:
        raise NotFound("Equipamento não encontrado.")
    valores = dict(anterior)
    valores.update(dados)
    Equipamento(
        nome=str(valores["nome"]),
        tipo=str(valores["tipo"]),
        quantidade=int(valores["quantidade"]),
        id_unidade=int(valores["idunidade"]) if valores["idunidade"] is not None else None,
    )
    equipamento = await store.update_equipamento(equipamento_id, dados)
    if equipamento is None:
        raise NotFound("Equipamento não encontrado.")
    return equipamento


async def excluir_equipamento(store: RegistryStore, equipamento_id: int) -> None:
    if not await store.delete_equipamento(equipamento_id):
        raise NotFound("Equipamento não encontrado.")
