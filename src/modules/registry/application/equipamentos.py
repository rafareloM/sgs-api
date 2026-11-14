"""Casos de uso dos equipamentos (spec 006, R5).

Rodam na transação da requisição: o repositório e o `AuditStore` recebidos estão presos à mesma
sessão, então o equipamento e o registro de auditoria são gravados juntos ou nenhum dos dois
(AGENTS.md, regra 5).

Equipamento de unidade: a permissão (`equipamento:write` ou `unidade:read`) e o escopo sobre a
unidade já foram conferidos pelo `require` da rota (R5.1); as mudanças são auditadas no nível da
unidade, como `unidade.equipamento_*`, com a unidade como entidade e o id do equipamento nos
metadados, para entrarem no histórico dela (R5.3, design § Diff e auditoria). Os campos vão com
os nomes da API e o prefixo `equipamento.`, para não se confundirem com os da unidade.

Equipamento sem unidade (R5.2): só com `equipamento:write` global, conferido aqui. Sem unidade
para levar o evento, `equipamento.criado` tem o próprio equipamento como entidade.
"""

from collections.abc import Mapping
from dataclasses import replace
from typing import Any
from uuid import UUID

from src.core.errors import NotFound
from src.modules.access.application.autorizacao import UsuarioAtual
from src.modules.audit.application.registrar import Ator, AuditStore, Mudanca
from src.modules.registry.application.vinculados import (
    NAO_EXISTE,
    Vinculado,
    da_unidade,
    exigir_global,
    invalido,
)
from src.modules.registry.domain.equipamento import (
    CAMPOS_DO_EQUIPAMENTO,
    DadosDoEquipamento,
    Equipamento,
)
from src.modules.registry.domain.ports import RepositorioDeEquipamentos
from src.modules.registry.domain.unidade import diff

# Reexportados para a camada api, que só importa a application.
__all__ = [
    "DadosDoEquipamento",
    "Equipamento",
    "adicionar_equipamento",
    "alterar_equipamento",
    "listar_da_unidade",
    "listar_sem_unidade",
    "remover_equipamento",
]

PERMISSAO = "equipamento:write"

# Coluna → nome da API, para a auditoria e o 422.
_EQUIPAMENTO = Vinculado(
    substantivo="equipamento",
    campo_da_api={
        "name": "nome",
        "cnes": "cnes",
        "equipment_type_code": "tipo_equipamento_codigo",
        "quantity": "quantidade",
        "status": "status",
    },
)


async def listar_da_unidade(
    unidade_id: UUID, *, equipamentos: RepositorioDeEquipamentos
) -> list[Equipamento]:
    """006/R5.1: os equipamentos da unidade. A rota já conferiu `unidade:read` e que a unidade
    existe."""
    return await equipamentos.da_unidade(unidade_id)


async def listar_sem_unidade(
    *, usuario: UsuarioAtual, equipamentos: RepositorioDeEquipamentos
) -> list[Equipamento]:
    """006/R5.2: os equipamentos sem unidade, só para quem tem `equipamento:write` global."""
    exigir_global(usuario, PERMISSAO)
    return await equipamentos.sem_unidade()


async def adicionar_equipamento(
    unidade_id: UUID | None,
    dados: DadosDoEquipamento,
    *,
    novo_id: UUID,
    usuario: UsuarioAtual,
    ator: Ator,
    equipamentos: RepositorioDeEquipamentos,
    auditoria: AuditStore,
) -> Equipamento:
    """Grava o equipamento na unidade (006/R5.1) ou, com `unidade_id` nulo, sem unidade (R5.2),
    e o audita com todos os campos (R5.3).

    Levanta `AcessoNegado` (403) se é sem unidade e o usuário não tem `equipamento:write` global,
    e `DomainValidationError` (422) se o tipo não existe ou está desativado.
    """
    if unidade_id is None:
        exigir_global(usuario, PERMISSAO)
    await _exigir_tipo_ativo(dados.equipment_type_code, equipamentos)
    equipamento = await equipamentos.inserir(novo_id, unidade_id, dados)
    mudancas = [
        Mudanca(campo=campo, de=None, para=valor)
        for campo, valor in equipamento.campos_de_negocio().items()
    ]
    if unidade_id is None:
        await _EQUIPAMENTO.auditar_sem_unidade(auditoria, ator, equipamento, mudancas)
    else:
        await _EQUIPAMENTO.auditar_na_unidade(auditoria, "criado", ator, equipamento, mudancas)
    return equipamento


async def alterar_equipamento(
    unidade_id: UUID,
    equipamento_id: UUID,
    alteracoes: Mapping[str, object],
    *,
    ator: Ator,
    equipamentos: RepositorioDeEquipamentos,
    auditoria: AuditStore,
) -> Equipamento:
    """Aplica ao equipamento da unidade só os campos de `alteracoes` (nomes das colunas) e o
    devolve como ficou (006/R5.1); registra `unidade.equipamento_atualizado` com cada campo que
    mudou (R5.3). Sem mudança, devolve como está, sem gravar nem auditar.

    Levanta `NotFound` (404) se o equipamento não existe ou não é dessa unidade, e
    `DomainValidationError` (422) se o tipo novo não existe ou está desativado.
    """
    atual = await da_unidade(equipamentos.ler, unidade_id, equipamento_id)
    enviados = {c: alteracoes[c] for c in CAMPOS_DO_EQUIPAMENTO if c in alteracoes}
    mudancas = diff(atual.campos_de_negocio(), enviados)
    if not mudancas:
        return atual
    valores: dict[str, Any] = {m.campo: m.para for m in mudancas}
    if "equipment_type_code" in valores:
        await _exigir_tipo_ativo(valores["equipment_type_code"], equipamentos)
    gravado = await equipamentos.atualizar(equipamento_id, replace(atual, **valores))
    if gravado is None:
        raise NotFound(NAO_EXISTE)
    await _EQUIPAMENTO.auditar_na_unidade(
        auditoria,
        "atualizado",
        ator,
        gravado,
        [Mudanca(campo=m.campo, de=m.de, para=m.para) for m in mudancas],
    )
    return gravado


async def remover_equipamento(
    unidade_id: UUID,
    equipamento_id: UUID,
    *,
    ator: Ator,
    equipamentos: RepositorioDeEquipamentos,
    auditoria: AuditStore,
) -> None:
    """Apaga o equipamento da unidade (006/R5.1; exclusão física, decisão U5 da 011) e registra
    `unidade.equipamento_removido` com os campos que ele tinha (R5.3). Os serviços dele ficam na
    unidade (011/R9.1). Levanta `NotFound` (404) se ele não existe ou não é dessa unidade."""
    atual = await da_unidade(equipamentos.ler, unidade_id, equipamento_id)
    if not await equipamentos.remover(equipamento_id):
        raise NotFound(NAO_EXISTE)
    await _EQUIPAMENTO.auditar_na_unidade(
        auditoria,
        "removido",
        ator,
        atual,
        [
            Mudanca(campo=campo, de=valor, para=None)
            for campo, valor in atual.campos_de_negocio().items()
        ],
    )


async def _exigir_tipo_ativo(codigo: str, equipamentos: RepositorioDeEquipamentos) -> None:
    if not await equipamentos.tipo_ativo(codigo):
        raise invalido("tipo_equipamento_codigo", "Tipo de equipamento inexistente ou desativado.")
