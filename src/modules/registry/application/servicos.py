"""Casos de uso dos serviços (spec 006, R6).

Rodam na transação da requisição: o repositório e o `AuditStore` recebidos estão presos à mesma
sessão, então o serviço e o registro de auditoria são gravados juntos ou nenhum dos dois
(AGENTS.md, regra 5).

Serviço de unidade: a permissão (`servico:write` ou `unidade:read`) e o escopo sobre a unidade
já foram conferidos pelo `require` da rota (R6.1); as mudanças são auditadas no nível da
unidade, como `unidade.servico_*`, com a unidade como entidade e o id do serviço nos metadados,
para entrarem no histórico dela (design § Diff e auditoria). Os campos vão com os nomes da API e
o prefixo `servico.`, para não se confundirem com os da unidade.

Serviço solto (R6.2): só com `servico:write` global, conferido aqui. Sem unidade para levar o
evento, `servico.criado` tem o próprio serviço como entidade.

O serviço aponta a unidade e o equipamento pelo id (R6.4): renomear a unidade não toca nele.
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
from src.modules.registry.domain.ports import RepositorioDeServicos
from src.modules.registry.domain.servico import CAMPOS_DO_SERVICO, DadosDoServico, Servico
from src.modules.registry.domain.unidade import diff

# Reexportados para a camada api, que só importa a application.
__all__ = [
    "DadosDoServico",
    "Servico",
    "adicionar_servico",
    "alterar_servico",
    "listar_da_unidade",
    "listar_soltos",
    "remover_servico",
]

PERMISSAO = "servico:write"


def _para_json(valor: object) -> object:
    """O id do equipamento vai como texto na trilha (JSONB)."""
    return str(valor) if isinstance(valor, UUID) else valor


# Coluna → nome da API, para a auditoria e o 422.
_SERVICO = Vinculado(
    substantivo="servico",
    campo_da_api={
        "service_type_id": "tipo_servico_id",
        "equipment_id": "equipamento_id",
        "name": "nome",
        "in_cnes": "no_cnes",
        "status": "status",
    },
    para_json=_para_json,
)


async def listar_da_unidade(unidade_id: UUID, *, servicos: RepositorioDeServicos) -> list[Servico]:
    """006/R6.1: os serviços da unidade. A rota já conferiu `unidade:read` e que a unidade
    existe."""
    return await servicos.da_unidade(unidade_id)


async def listar_soltos(*, usuario: UsuarioAtual, servicos: RepositorioDeServicos) -> list[Servico]:
    """006/R6.2: os serviços soltos, só para quem tem `servico:write` global."""
    exigir_global(usuario, PERMISSAO)
    return await servicos.soltos()


async def adicionar_servico(
    unidade_id: UUID | None,
    dados: DadosDoServico,
    *,
    novo_id: UUID,
    usuario: UsuarioAtual,
    ator: Ator,
    servicos: RepositorioDeServicos,
    auditoria: AuditStore,
) -> Servico:
    """Grava o serviço na unidade (006/R6.1) ou, com `unidade_id` nulo, solto (R6.2), e o
    audita com todos os campos.

    Levanta `AcessoNegado` (403) se é solto e o usuário não tem `servico:write` global, e
    `DomainValidationError` (422) se o tipo não existe ou está desativado, ou se o equipamento
    não é da mesma unidade (no solto, se não é equipamento sem unidade).
    """
    if unidade_id is None:
        exigir_global(usuario, PERMISSAO)
    await _exigir_tipo_ativo(dados.service_type_id, servicos)
    await _exigir_equipamento_da_unidade(dados.equipment_id, unidade_id, servicos)
    servico = await servicos.inserir(novo_id, unidade_id, dados)
    mudancas = [
        Mudanca(campo=campo, de=None, para=valor)
        for campo, valor in servico.campos_de_negocio().items()
    ]
    if unidade_id is None:
        await _SERVICO.auditar_sem_unidade(auditoria, ator, servico, mudancas)
    else:
        await _SERVICO.auditar_na_unidade(auditoria, "criado", ator, servico, mudancas)
    return servico


async def alterar_servico(
    unidade_id: UUID,
    servico_id: UUID,
    alteracoes: Mapping[str, object],
    *,
    ator: Ator,
    servicos: RepositorioDeServicos,
    auditoria: AuditStore,
) -> Servico:
    """Aplica ao serviço da unidade só os campos de `alteracoes` (nomes das colunas) e o devolve
    como ficou (006/R6.1); registra `unidade.servico_atualizado` com cada campo que mudou. Sem
    mudança, devolve como está, sem gravar nem auditar.

    Levanta `NotFound` (404) se o serviço não existe ou não é dessa unidade, e
    `DomainValidationError` (422) se o tipo novo não existe ou está desativado, ou se o
    equipamento novo não é da unidade.
    """
    atual = await da_unidade(servicos.ler, unidade_id, servico_id)
    enviados = {c: alteracoes[c] for c in CAMPOS_DO_SERVICO if c in alteracoes}
    mudancas = diff(atual.campos_de_negocio(), enviados)
    if not mudancas:
        return atual
    valores: dict[str, Any] = {m.campo: m.para for m in mudancas}
    if "service_type_id" in valores:
        await _exigir_tipo_ativo(valores["service_type_id"], servicos)
    if "equipment_id" in valores:
        await _exigir_equipamento_da_unidade(valores["equipment_id"], unidade_id, servicos)
    gravado = await servicos.atualizar(servico_id, replace(atual, **valores))
    if gravado is None:
        raise NotFound(NAO_EXISTE)
    await _SERVICO.auditar_na_unidade(
        auditoria,
        "atualizado",
        ator,
        gravado,
        [Mudanca(campo=m.campo, de=m.de, para=m.para) for m in mudancas],
    )
    return gravado


async def remover_servico(
    unidade_id: UUID,
    servico_id: UUID,
    *,
    ator: Ator,
    servicos: RepositorioDeServicos,
    auditoria: AuditStore,
) -> None:
    """Apaga o serviço da unidade (006/R6.1; exclusão física, decisão U5 da 011) e registra
    `unidade.servico_removido` com os campos que ele tinha. Levanta `NotFound` (404) se ele não
    existe ou não é dessa unidade."""
    atual = await da_unidade(servicos.ler, unidade_id, servico_id)
    if not await servicos.remover(servico_id):
        raise NotFound(NAO_EXISTE)
    await _SERVICO.auditar_na_unidade(
        auditoria,
        "removido",
        ator,
        atual,
        [
            Mudanca(campo=campo, de=valor, para=None)
            for campo, valor in atual.campos_de_negocio().items()
        ],
    )


async def _exigir_tipo_ativo(tipo_id: int, servicos: RepositorioDeServicos) -> None:
    if not await servicos.tipo_ativo(tipo_id):
        raise invalido("tipo_servico_id", "Tipo de serviço inexistente ou desativado.")


async def _exigir_equipamento_da_unidade(
    equipamento_id: UUID | None, unidade_id: UUID | None, servicos: RepositorioDeServicos
) -> None:
    """O equipamento do serviço é da mesma unidade; no serviço solto, é sem unidade."""
    if equipamento_id is None:
        return
    if not await servicos.equipamento_na_unidade(equipamento_id, unidade_id):
        raise invalido(
            "equipamento_id",
            "Equipamento inexistente ou de outra unidade."
            if unidade_id is not None
            else "Equipamento inexistente ou de uma unidade.",
        )
