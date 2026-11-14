"""Casos de uso da unidade de saúde (spec 006).

Rodam na transação da requisição: o repositório e o `AuditStore` recebidos estão presos à mesma
sessão, então a unidade e o registro de auditoria são gravados juntos ou nenhum dos dois
(AGENTS.md, regra 5).
"""

from collections.abc import Mapping
from dataclasses import replace
from decimal import Decimal
from typing import Any
from uuid import UUID

from src.core.errors import (
    Conflict,
    DomainValidationError,
    FieldError,
    NotFound,
    PreconditionFailed,
)
from src.modules.access.application.autorizacao import (
    Alvo,
    Recurso,
    UsuarioAtual,
    escopo_de_leitura,
    exigir_na_area,
    exigir_no_escopo,
)
from src.modules.audit.application.registrar import (
    Ator,
    AuditStore,
    Entidade,
    Mudanca,
    registrar,
)
from src.modules.registry.domain.busca import (
    DetalheDaUnidade,
    EquipamentoDaUnidade,
    FiltrosDeUnidades,
    Ordenacao,
    PaginaDeUnidades,
    PaginaPedida,
    ServicoDaUnidade,
    ordem_efetiva,
)
from src.modules.registry.domain.ports import RepositorioDeUnidades
from src.modules.registry.domain.unidade import (
    CAMPOS_DE_NEGOCIO,
    DadosDaUnidade,
    Unidade,
    UnidadeRepetidaError,
    campos_estruturais_alterados,
    diff,
)

# Reexportados para a camada api, que só importa a application.
__all__ = [
    "DadosDaUnidade",
    "DetalheDaUnidade",
    "EquipamentoDaUnidade",
    "FiltrosDeUnidades",
    "Ordenacao",
    "PaginaDeUnidades",
    "PaginaPedida",
    "ServicoDaUnidade",
    "Unidade",
    "atualizar_unidade",
    "buscar_unidades",
    "criar_unidade",
    "desativar_unidade",
    "detalhar_unidade",
]

# Permissão de leitura das unidades (matriz da 003).
LEITURA = "unidade:read"

# Nomes da API dos campos estruturais, para o 403 apontá-los (006/R3.4).
_CAMPO_DA_API = {"district_id": "distrito_id", "unit_type_id": "tipo_unidade_id", "cnes": "cnes"}

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


async def atualizar_unidade(
    unidade_id: UUID,
    alteracoes: Mapping[str, object],
    *,
    versao_esperada: int,
    usuario: UsuarioAtual,
    ator: Ator,
    unidades: RepositorioDeUnidades,
    auditoria: AuditStore,
) -> Unidade:
    """Aplica à unidade só os campos de `alteracoes` (nomes das colunas) e a devolve como ficou
    (006/R3.1), com a versão nova que o trigger da 011 deu (R8); aqui ela nunca é incrementada.

    A permissão e o escopo sobre a unidade já foram conferidos pelo `require` da rota (R3.3).
    Levanta `PreconditionFailed` (412) se a unidade não está mais na `versao_esperada`, mudada pela
    API ou fora dela (R3.2; 011/R8.3); `AcessoNegado` (403), apontando os campos, se muda
    distrito, tipo ou CNES sem escopo global ou na área técnica da unidade (R3.4), ou se troca o
    tipo por um de área técnica fora do escopo do usuário (R1.1);
    `DomainValidationError` (422) se o tipo ou o distrito novo não existe ou está desativado;
    `Conflict` (409) se repete o CNES ou o nome no distrito de outra (R1.3, R1.4); `NotFound`
    (404) se a unidade não existe. Registra `unidade.atualizada` com `{campo, de, para}` de cada
    campo que mudou, na mesma transação (R3.5); sem mudança, devolve a unidade como está, sem
    gravar nem auditar (R3.6).
    """
    atual = await unidades.ler(unidade_id)
    if atual is None:
        raise NotFound("O recurso pedido não existe.")
    if atual.version != versao_esperada:
        raise _versao_desatualizada()
    enviados = {campo: alteracoes[campo] for campo in CAMPOS_DE_NEGOCIO if campo in alteracoes}
    mudancas = diff(atual.campos_de_negocio(), enviados)
    if not mudancas:
        return atual
    valores: dict[str, Any] = {m.campo: m.para for m in mudancas}
    novos = replace(atual, **valores)
    estruturais = campos_estruturais_alterados(mudancas)
    if estruturais:
        area = await unidades.area_da_unidade(unidade_id)
        if area is None:
            raise NotFound("O recurso pedido não existe.")
        recurso = Recurso(tipo=ENTIDADE, id=str(unidade_id))
        extensoes = {"campos": [_CAMPO_DA_API[campo] for campo in estruturais]}
        exigir_na_area(usuario, "unidade:update", area, recurso=recurso, extensoes=extensoes)
        # O tipo novo decide a área para onde a unidade vai: ela também precisa estar no escopo,
        # como no cadastro (R1.1). Tipo inexistente cai no 422 de `_conferir_referencias`.
        if "unit_type_id" in estruturais:
            area_nova = await unidades.area_do_tipo(novos.unit_type_id)
            if area_nova is not None and area_nova != area:
                exigir_na_area(
                    usuario, "unidade:update", area_nova, recurso=recurso, extensoes=extensoes
                )
    await _conferir_referencias(novos, estruturais, unidades)
    try:
        gravada = await unidades.atualizar(unidade_id, versao_esperada, novos)
    except UnidadeRepetidaError:
        raise await _conflito(novos, unidades, exceto=unidade_id) from None
    if gravada is None:
        raise _versao_desatualizada()
    await registrar(
        auditoria,
        acao="unidade.atualizada",
        ator=ator,
        entidade=Entidade(tipo=ENTIDADE, id=str(unidade_id)),
        mudancas=[Mudanca(campo=m.campo, de=_json(m.de), para=_json(m.para)) for m in mudancas],
    )
    return gravada


async def desativar_unidade(
    unidade_id: UUID,
    *,
    motivo: str,
    ator: Ator,
    unidades: RepositorioDeUnidades,
    auditoria: AuditStore,
) -> Unidade:
    """Desativa a unidade (006/R4.1) pelo procedimento do banco e a devolve como ficou (011/R6.2).

    A permissão e o escopo já foram conferidos pelo `require` da rota, sobre a própria unidade.
    Registra `unidade.desativada` com o status de antes e o motivo, na mesma transação, só quando
    o status muda: unidade que já estava inativa volta como está, sem auditoria (011/R6.4). Nada
    é apagado (006/R4.2). Levanta `NotFound` (404), com detalhe fixo, se a unidade não existe
    (011/R6.3).
    """
    desativacao = await unidades.desativar(unidade_id)
    if desativacao is None:
        raise NotFound("O recurso pedido não existe.")
    if desativacao.mudou:
        await registrar(
            auditoria,
            acao="unidade.desativada",
            ator=ator,
            entidade=Entidade(tipo=ENTIDADE, id=str(unidade_id)),
            mudancas=[
                Mudanca(
                    campo="status",
                    de=desativacao.status_anterior,
                    para=desativacao.unidade.status,
                )
            ],
            metadados={"motivo": motivo},
        )
    return desativacao.unidade


async def buscar_unidades(
    filtros: FiltrosDeUnidades,
    ordem: Ordenacao | None,
    pagina: PaginaPedida,
    *,
    usuario: UsuarioAtual,
    unidades: RepositorioDeUnidades,
) -> PaginaDeUnidades:
    """Uma página das unidades no escopo de leitura do usuário (006/R2.6) que passam pelos
    filtros (R2.2, R2.3), na ordem pedida (R2.4), com o total (R2.1). Sem ordem pedida, a mais
    parecida com o texto livre vem primeiro, se houver texto; senão, por nome (design § Busca).
    A permissão já foi conferida pelo `require` da rota; aqui só se limita o escopo."""
    escopo = escopo_de_leitura(usuario, LEITURA)
    return await unidades.buscar(escopo, filtros, ordem_efetiva(ordem, filtros), pagina)


async def detalhar_unidade(
    unidade_id: UUID, *, unidades: RepositorioDeUnidades
) -> DetalheDaUnidade:
    """A unidade com os equipamentos e serviços vinculados (006/R2.5). A permissão e o escopo
    sobre ela já foram conferidos pelo `require` da rota (R2.6). Levanta `NotFound` (404) se ela
    não existe."""
    detalhe = await unidades.detalhar(unidade_id)
    if detalhe is None:
        raise NotFound("O recurso pedido não existe.")
    return detalhe


def _inexistente(campo: str, referencia: str) -> FieldError:
    """Erro do campo da API que aponta uma referência que não existe ou foi desativada."""
    return FieldError(campo=campo, mensagem=f"{referencia} inexistente ou desativado.")


def _versao_desatualizada() -> PreconditionFailed:
    return PreconditionFailed(
        "A unidade mudou depois da versão informada em If-Match. Leia de novo e refaça a alteração."
    )


async def _conferir_referencias(
    dados: DadosDaUnidade, estruturais: list[str], unidades: RepositorioDeUnidades
) -> None:
    """422 se o tipo ou o distrito para o qual a unidade muda não existe ou está desativado,
    como no cadastro (006/R1.2). O que não muda não é conferido de novo."""
    erros: list[FieldError] = []
    if "unit_type_id" in estruturais and await unidades.area_do_tipo(dados.unit_type_id) is None:
        erros.append(_inexistente("tipo_unidade_id", "Tipo de unidade"))
    if "district_id" in estruturais and not await unidades.distrito_ativo(dados.district_id):
        erros.append(_inexistente("distrito_id", "Distrito"))
    if erros:
        raise DomainValidationError("A requisição tem campos inválidos.", errors=erros)


async def _conflito(
    dados: DadosDaUnidade, unidades: RepositorioDeUnidades, *, exceto: UUID | None = None
) -> Conflict:
    """O 409 de uma unidade que o banco recusou por repetir outra, apontando a existente.
    `exceto` é a própria unidade, numa atualização: ela não conflita consigo mesma."""
    existente = None if dados.cnes is None else await unidades.com_cnes(dados.cnes)
    if existente == exceto:
        existente = None
    if existente is not None:
        return Conflict(
            "Já existe uma unidade com este CNES.",
            extensoes={"unidade_existente_id": str(existente)},
        )
    existente = await unidades.com_nome(dados.district_id, dados.name)
    if existente == exceto:
        existente = None
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
