"""Casos de uso da unidade de saúde (spec 006).

Rodam na transação da requisição: o repositório e o `AuditStore` recebidos estão presos à mesma
sessão, então a unidade e o registro de auditoria são gravados juntos ou nenhum dos dois
(AGENTS.md, regra 5).
"""

from decimal import Decimal
from uuid import UUID

from src.core.errors import Conflict, DomainValidationError, FieldError
from src.modules.access.application.autorizacao import Alvo, UsuarioAtual, exigir_no_escopo
from src.modules.audit.application.registrar import (
    Ator,
    AuditStore,
    Entidade,
    Mudanca,
    registrar,
)
from src.modules.registry.domain.ports import RepositorioDeUnidades
from src.modules.registry.domain.unidade import DadosDaUnidade, Unidade

# Reexportados para a camada api, que só importa a application.
__all__ = ["DadosDaUnidade", "Unidade", "criar_unidade"]

# `entity_type` dos eventos da unidade, também nos de equipamento e serviço (006/R5.3).
ENTIDADE = "unidade"


async def criar_unidade(
    dados: DadosDaUnidade,
    *,
    novo_id: UUID,
    usuario: UsuarioAtual,
    ator: Ator,
    unidades: RepositorioDeUnidades,
    auditoria: AuditStore,
) -> Unidade:
    """Cria a unidade (006/R1) e registra `unidade.criada` com todos os campos (R1.6).

    Levanta `DomainValidationError` (422) se o tipo ou o distrito não existe ou está desativado
    (R1.2), `AcessoNegado` (403) se o usuário não tem `unidade:create` no escopo da área técnica
    do tipo (R1.1), e `Conflict` (409) se o CNES já é de outra unidade (R1.3) ou se outra do
    mesmo distrito tem o mesmo nome normalizado (R1.4); os dois apontam a existente.
    """
    area = await unidades.area_do_tipo(dados.unit_type_id)
    erros: list[FieldError] = []
    if area is None:
        erros.append(_inexistente("tipo_unidade_id", "Tipo de unidade"))
    if not await unidades.distrito_ativo(dados.district_id):
        erros.append(_inexistente("distrito_id", "Distrito"))
    if area is None or erros:
        raise DomainValidationError("A requisição tem campos inválidos.", errors=erros)
    exigir_no_escopo(
        usuario,
        "unidade:create",
        Alvo(unidade_id=novo_id, distrito_id=dados.district_id, area_id=area),
    )
    unidade = await unidades.inserir(novo_id, dados)
    if unidade is None:
        raise await _conflito(dados, unidades)
    await registrar(
        auditoria,
        acao="unidade.criada",
        ator=ator,
        entidade=Entidade(tipo=ENTIDADE, id=str(unidade.id)),
        mudancas=[
            Mudanca(campo=campo, de=None, para=_json(valor))
            for campo, valor in unidade.campos_de_negocio().items()
        ],
    )
    return unidade


def _inexistente(campo: str, referencia: str) -> FieldError:
    """Erro do campo da API que aponta uma referência que não existe ou foi desativada."""
    return FieldError(campo=campo, mensagem=f"{referencia} inexistente ou desativado.")


async def _conflito(dados: DadosDaUnidade, unidades: RepositorioDeUnidades) -> Conflict:
    """O 409 de uma unidade que o banco recusou por repetir outra, apontando a existente."""
    existente = None if dados.cnes is None else await unidades.com_cnes(dados.cnes)
    if existente is not None:
        return Conflict(
            "Já existe uma unidade com este CNES.",
            extensoes={"unidade_existente_id": str(existente)},
        )
    existente = await unidades.com_nome(dados.district_id, dados.name)
    if existente is not None:
        return Conflict(
            "Já existe uma unidade com este nome no distrito.",
            extensoes={"unidade_existente_id": str(existente)},
        )
    # Só sobra a chave primária, que um UUID v7 novo não repete na prática.
    return Conflict("Já existe uma unidade com estes dados.")


def _json(valor: object) -> object:
    """O valor como a trilha o guarda: JSON (coordenadas `numeric` viram número)."""
    return float(valor) if isinstance(valor, Decimal) else valor
