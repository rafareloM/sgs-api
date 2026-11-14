"""Casos de uso das tabelas de referência (spec 006, R7; spec 011, R9.2).

A permissão (`regra_validacao:manage`, só do Gestor de Dados) é conferida pelo `require` da rota.
Rodam na transação da requisição: o item e o registro de auditoria são gravados juntos ou nenhum
dos dois (AGENTS.md, regra 5).
"""

from collections.abc import Mapping

from src.core.errors import Conflict, DomainValidationError, FieldError, NotFound
from src.modules.audit.application.registrar import Ator, AuditStore, Entidade, Mudanca, registrar
from src.modules.registry.domain.ports import RepositorioDeReferencias
from src.modules.registry.domain.referencia import (
    CodigoRepetidoError,
    DadosDaReferencia,
    Referencia,
    TipoDeReferencia,
)
from src.modules.registry.domain.unidade import diff

# Reexportados para a camada api, que só importa a application.
__all__ = [
    "DadosDaReferencia",
    "Referencia",
    "TipoDeReferencia",
    "alterar_referencia",
    "criar_referencia",
    "listar_referencias",
]

_CODIGO_REPETIDO = "Já existe um item com este código."


async def listar_referencias(
    tipo: TipoDeReferencia, *, referencias: RepositorioDeReferencias
) -> list[Referencia]:
    """006/R7.1: os itens da tabela, para preencher formulários."""
    return await referencias.listar(tipo)


async def criar_referencia(
    tipo: TipoDeReferencia,
    dados: DadosDaReferencia,
    *,
    ator: Ator,
    referencias: RepositorioDeReferencias,
    auditoria: AuditStore,
) -> Referencia:
    """Inclui um item (006/R7.2) e registra `referencia.criada` com os campos dele.

    Levanta `DomainValidationError` (422) se a área técnica do tipo de unidade não existe ou está
    desativada, e `Conflict` (409) se o código já é de outro item.
    """
    if dados.area_tecnica_id is not None:
        await _exigir_area_ativa(dados.area_tecnica_id, referencias)
    item = await referencias.inserir(tipo, dados)
    if item is None:
        raise Conflict(_CODIGO_REPETIDO)
    await registrar(
        auditoria,
        acao="referencia.criada",
        ator=ator,
        entidade=Entidade(tipo=tipo.value, id=str(item.id)),
        mudancas=[
            Mudanca(campo=campo, de=None, para=valor) for campo, valor in item.campos(tipo).items()
        ],
    )
    return item


async def alterar_referencia(
    tipo: TipoDeReferencia,
    id_: int,
    mudancas: Mapping[str, object],
    *,
    ator: Ator,
    referencias: RepositorioDeReferencias,
    auditoria: AuditStore,
) -> Referencia:
    """Altera código, nome, `ativo` (desativar ou reativar) ou, no tipo de unidade, a área
    técnica (006/R7.2), e registra `referencia.atualizada` com o de/para do que mudou.

    Corrigir o código de um tipo de equipamento leva o código novo aos equipamentos dele, e a
    auditoria traz `equipamentos_afetados` (006/R7.3, 011/R9.2). Nada mudou → nada é auditado.
    Levanta `NotFound` (404), `Conflict` (409, código repetido) e `DomainValidationError` (422,
    área técnica inexistente ou desativada).
    """
    area = mudancas.get("area_tecnica_id")
    if isinstance(area, int):
        await _exigir_area_ativa(area, referencias)
    try:
        alteracao = await referencias.atualizar(tipo, id_, dict(mudancas))
    except CodigoRepetidoError:
        raise Conflict(_CODIGO_REPETIDO) from None
    if alteracao is None:
        raise NotFound("O recurso pedido não existe.")
    depois = alteracao.depois.campos(tipo)
    enviados = {campo: depois[campo] for campo in mudancas if campo in depois}
    mudou = diff(alteracao.antes.campos(tipo), enviados)
    if not mudou:
        return alteracao.depois
    metadados: dict[str, object] | None = None
    if tipo is TipoDeReferencia.TIPO_EQUIPAMENTO and any(m.campo == "codigo" for m in mudou):
        afetados = await referencias.equipamentos_do_tipo(alteracao.depois.codigo)
        metadados = {"equipamentos_afetados": afetados}
    await registrar(
        auditoria,
        acao="referencia.atualizada",
        ator=ator,
        entidade=Entidade(tipo=tipo.value, id=str(id_)),
        mudancas=[Mudanca(campo=m.campo, de=m.de, para=m.para) for m in mudou],
        metadados=metadados,
    )
    return alteracao.depois


async def _exigir_area_ativa(area_tecnica_id: int, referencias: RepositorioDeReferencias) -> None:
    if not await referencias.area_ativa(area_tecnica_id):
        raise DomainValidationError(
            "A requisição tem campos inválidos.",
            errors=[
                FieldError(
                    campo="area_tecnica_id", mensagem="Área técnica inexistente ou desativada."
                )
            ],
        )
