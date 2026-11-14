"""Rotas dos equipamentos (design da 006 § Rotas; R5).

`/unidades/{id}/equipamentos`: listar com `unidade:read`; adicionar, alterar e remover com
`equipamento:write`, as duas no escopo da unidade (R5.1). `/equipamentos`: equipamentos sem
unidade, com `equipamento:write` global, o do Gestor de Dados (R5.2), conferido pelo caso de uso.
"""

from datetime import datetime
from typing import Annotated, Any, Literal, Self
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.core.ids import uuid7
from src.core.problem import problema
from src.modules.access.api.deps import (
    ResourceRef,
    SessaoDeNegocio,
    UsuarioAtual,
    ator_da_requisicao,
    require,
)
from src.modules.registry.application.equipamentos import (
    DadosDoEquipamento,
    Equipamento,
    adicionar_equipamento,
    alterar_equipamento,
    listar_da_unidade,
    listar_sem_unidade,
    remover_equipamento,
)

router = APIRouter(prefix="/api/v1", tags=["equipamentos"])

StatusDoEquipamento = Literal["ativo", "inativo", "em_implantacao"]

# `[0-9]` e não `\d`, que no Pydantic também aceita dígitos de outros alfabetos.
_Cnes = Annotated[str, Field(pattern=r"^[0-9]{7}$", description="Sete dígitos.")]
_Nome = Annotated[str, Field(min_length=1, max_length=200)]
# `equipment_types.code` é `varchar(50)`.
_CodigoDoTipo = Annotated[
    str, Field(min_length=1, max_length=50, description="Código do tipo de equipamento.")
]
_Quantidade = Annotated[int, Field(ge=1, le=2_147_483_647)]


class EquipamentoCreate(BaseModel):
    """Equipamento novo: nome, tipo e status obrigatórios; sem quantidade, vale 1."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    nome: _Nome
    cnes: _Cnes | None = None
    tipo_equipamento_codigo: _CodigoDoTipo
    quantidade: _Quantidade = 1
    status: StatusDoEquipamento

    def dados(self) -> DadosDoEquipamento:
        return DadosDoEquipamento(
            name=self.nome,
            cnes=self.cnes,
            equipment_type_code=self.tipo_equipamento_codigo,
            quantity=self.quantidade,
            status=self.status,
        )


# Campo da API → coluna, para os campos que o PATCH aceita (os mesmos do cadastro).
_COLUNA = {
    "nome": "name",
    "cnes": "cnes",
    "tipo_equipamento_codigo": "equipment_type_code",
    "quantidade": "quantity",
    "status": "status",
}


class EquipamentoUpdate(BaseModel):
    """Alteração parcial: só os campos enviados mudam. CNES nulo é apagado; os obrigatórios do
    cadastro podem faltar, mas não vir nulos. A unidade do equipamento não muda por aqui."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    nome: _Nome | None = None
    cnes: _Cnes | None = None
    tipo_equipamento_codigo: _CodigoDoTipo | None = None
    quantidade: _Quantidade | None = None
    status: StatusDoEquipamento | None = None

    @field_validator("nome", "tipo_equipamento_codigo", "quantidade", "status")
    @classmethod
    def _sem_nulo(cls, valor: object) -> object:
        # Roda só para o campo enviado; o ausente fica com o padrão e não é validado.
        if valor is None:
            raise ValueError("Campo obrigatório: não pode ser nulo.")
        return valor

    def alteracoes(self) -> dict[str, object]:
        """Coluna → valor, só dos campos enviados."""
        return {_COLUNA[campo]: getattr(self, campo) for campo in self.model_fields_set}


class EquipamentoOut(BaseModel):
    """O equipamento; `unidade_id` nulo é o equipamento sem unidade (006/R5.2)."""

    id: UUID
    unidade_id: UUID | None
    nome: str
    cnes: str | None
    tipo_equipamento_codigo: str
    quantidade: int
    status: str
    criado_em: datetime
    atualizado_em: datetime

    @classmethod
    def de(cls, equipamento: Equipamento) -> Self:
        return cls(
            id=equipamento.id,
            unidade_id=equipamento.unit_id,
            nome=equipamento.name,
            cnes=equipamento.cnes,
            tipo_equipamento_codigo=equipamento.equipment_type_code,
            quantidade=equipamento.quantity,
            status=equipamento.status,
            criado_em=equipamento.created_at,
            atualizado_em=equipamento.updated_at,
        )


@router.get(
    "/unidades/{id}/equipamentos",
    summary="Listar equipamentos da unidade",
    responses={
        401: problema("Sem access token válido"),
        403: problema("Sem `unidade:read` no escopo da unidade"),
        404: problema("A unidade não existe"),
    },
)
async def listar(
    request: Request,
    id: UUID,
    usuario: Annotated[UsuarioAtual, Depends(require("unidade:read", ResourceRef("unidade")))],
    sessao: SessaoDeNegocio,
) -> list[EquipamentoOut]:
    """006/R5.1: os equipamentos da unidade, pela ordem de cadastro."""
    estado = request.app.state
    equipamentos = await listar_da_unidade(
        id, equipamentos=estado.repositorio_de_equipamentos(sessao)
    )
    return [EquipamentoOut.de(e) for e in equipamentos]


@router.post(
    "/unidades/{id}/equipamentos",
    status_code=201,
    summary="Adicionar equipamento à unidade",
    responses={
        401: problema("Sem access token válido"),
        403: problema("Sem `equipamento:write` no escopo da unidade"),
        404: problema("A unidade não existe"),
        422: problema("Campos inválidos, ou tipo de equipamento inexistente ou desativado"),
    },
)
async def adicionar(
    request: Request,
    response: Response,
    id: UUID,
    corpo: EquipamentoCreate,
    usuario: Annotated[UsuarioAtual, Depends(require("equipamento:write", ResourceRef("unidade")))],
    sessao: SessaoDeNegocio,
) -> EquipamentoOut:
    """006/R5.1, R5.3: grava o equipamento na unidade e audita `unidade.equipamento_criado`."""
    equipamento = await _adicionar(request, id, corpo, usuario, sessao)
    # A rota do equipamento na unidade, a mesma do PATCH e do DELETE.
    response.headers["Location"] = f"/api/v1/unidades/{id}/equipamentos/{equipamento.id}"
    return EquipamentoOut.de(equipamento)


@router.patch(
    "/unidades/{id}/equipamentos/{eid}",
    summary="Alterar equipamento da unidade",
    responses={
        401: problema("Sem access token válido"),
        403: problema("Sem `equipamento:write` no escopo da unidade"),
        404: problema("A unidade ou o equipamento dela não existe"),
        422: problema("Campos inválidos, ou tipo de equipamento inexistente ou desativado"),
    },
)
async def alterar(
    request: Request,
    id: UUID,
    eid: UUID,
    corpo: EquipamentoUpdate,
    usuario: Annotated[UsuarioAtual, Depends(require("equipamento:write", ResourceRef("unidade")))],
    sessao: SessaoDeNegocio,
) -> EquipamentoOut:
    """006/R5.1, R5.3: aplica só os campos enviados e audita `unidade.equipamento_atualizado`
    com o que mudou; sem mudança, responde igual, sem alterar nem auditar."""
    estado = request.app.state
    equipamento = await alterar_equipamento(
        id,
        eid,
        corpo.alteracoes(),
        ator=ator_da_requisicao(request, usuario),
        equipamentos=estado.repositorio_de_equipamentos(sessao),
        auditoria=estado.auditoria(sessao),
    )
    return EquipamentoOut.de(equipamento)


@router.delete(
    "/unidades/{id}/equipamentos/{eid}",
    status_code=204,
    summary="Remover equipamento da unidade",
    responses={
        401: problema("Sem access token válido"),
        403: problema("Sem `equipamento:write` no escopo da unidade"),
        404: problema("A unidade ou o equipamento dela não existe"),
    },
)
async def remover(
    request: Request,
    id: UUID,
    eid: UUID,
    usuario: Annotated[UsuarioAtual, Depends(require("equipamento:write", ResourceRef("unidade")))],
    sessao: SessaoDeNegocio,
) -> None:
    """006/R5.1, R5.3: apaga o equipamento (os serviços dele ficam na unidade, 011/R9.1) e
    audita `unidade.equipamento_removido`."""
    estado = request.app.state
    await remover_equipamento(
        id,
        eid,
        ator=ator_da_requisicao(request, usuario),
        equipamentos=estado.repositorio_de_equipamentos(sessao),
        auditoria=estado.auditoria(sessao),
    )


@router.get(
    "/equipamentos",
    summary="Listar equipamentos sem unidade",
    responses={
        401: problema("Sem access token válido"),
        403: problema("Sem `equipamento:write` global"),
    },
)
async def listar_sem_unidade_(
    request: Request,
    usuario: Annotated[UsuarioAtual, Depends(require("equipamento:write"))],
    sessao: SessaoDeNegocio,
) -> list[EquipamentoOut]:
    """006/R5.2: os equipamentos sem unidade, pela ordem de cadastro, só para o Gestor de
    Dados."""
    estado = request.app.state
    equipamentos = await listar_sem_unidade(
        usuario=usuario, equipamentos=estado.repositorio_de_equipamentos(sessao)
    )
    return [EquipamentoOut.de(e) for e in equipamentos]


@router.post(
    "/equipamentos",
    status_code=201,
    summary="Cadastrar equipamento sem unidade",
    responses={
        401: problema("Sem access token válido"),
        403: problema("Sem `equipamento:write` global"),
        422: problema("Campos inválidos, ou tipo de equipamento inexistente ou desativado"),
    },
)
async def adicionar_sem_unidade(
    request: Request,
    corpo: EquipamentoCreate,
    usuario: Annotated[UsuarioAtual, Depends(require("equipamento:write"))],
    sessao: SessaoDeNegocio,
) -> EquipamentoOut:
    """006/R5.2: grava o equipamento sem unidade, como a UTI móvel, e audita
    `equipamento.criado`."""
    equipamento = await _adicionar(request, None, corpo, usuario, sessao)
    return EquipamentoOut.de(equipamento)


async def _adicionar(
    request: Request,
    unidade_id: UUID | None,
    corpo: EquipamentoCreate,
    usuario: UsuarioAtual,
    sessao: Any,
) -> Equipamento:
    estado = request.app.state
    return await adicionar_equipamento(
        unidade_id,
        corpo.dados(),
        novo_id=uuid7(),
        usuario=usuario,
        ator=ator_da_requisicao(request, usuario),
        equipamentos=estado.repositorio_de_equipamentos(sessao),
        auditoria=estado.auditoria(sessao),
    )
