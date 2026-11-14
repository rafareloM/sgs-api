"""Rotas dos serviços (design da 006 § Rotas; R6).

`/unidades/{id}/servicos`: listar com `unidade:read`; adicionar, alterar e remover com
`servico:write`, as duas no escopo da unidade (R6.1). `/servicos`: serviços soltos, com
`servico:write` global, o do Gestor de Dados (R6.2), conferido pelo caso de uso.
"""

from datetime import datetime
from typing import Annotated, Any, Literal, Self
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator

from src.core.ids import uuid7
from src.core.problem import problema
from src.modules.access.api.deps import (
    ResourceRef,
    SessaoDeNegocio,
    UsuarioAtual,
    ator_da_requisicao,
    require,
)
from src.modules.registry.application.servicos import (
    DadosDoServico,
    Servico,
    adicionar_servico,
    alterar_servico,
    listar_da_unidade,
    listar_soltos,
    remover_servico,
)

router = APIRouter(prefix="/api/v1", tags=["servicos"])

StatusDoServico = Literal["ativo", "inativo", "em_implantacao"]

_Nome = Annotated[str, Field(min_length=1, max_length=200)]
# `service_types.id` é `smallserial`.
_IdDoTipo = Annotated[int, Field(ge=1, le=32767, description="Id do tipo de serviço.")]
_NoCnes = Annotated[StrictBool, Field(description="Se o serviço consta no CNES.")]
_IdDoEquipamento = Annotated[
    UUID, Field(description="Equipamento em que o serviço é ofertado, da mesma unidade.")
]


class ServicoCreate(BaseModel):
    """Serviço novo: nome, tipo e status obrigatórios; sem `no_cnes`, não consta no CNES."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    nome: _Nome
    tipo_servico_id: _IdDoTipo
    equipamento_id: _IdDoEquipamento | None = None
    no_cnes: _NoCnes = False
    status: StatusDoServico

    def dados(self) -> DadosDoServico:
        return DadosDoServico(
            service_type_id=self.tipo_servico_id,
            equipment_id=self.equipamento_id,
            name=self.nome,
            in_cnes=self.no_cnes,
            status=self.status,
        )


# Campo da API → coluna, para os campos que o PATCH aceita (os mesmos do cadastro).
_COLUNA = {
    "tipo_servico_id": "service_type_id",
    "equipamento_id": "equipment_id",
    "nome": "name",
    "no_cnes": "in_cnes",
    "status": "status",
}


class ServicoUpdate(BaseModel):
    """Alteração parcial: só os campos enviados mudam. `equipamento_id` nulo desliga o serviço
    do equipamento; os outros podem faltar, mas não vir nulos. A unidade do serviço não muda
    por aqui."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    nome: _Nome | None = None
    tipo_servico_id: _IdDoTipo | None = None
    equipamento_id: _IdDoEquipamento | None = None
    no_cnes: _NoCnes | None = None
    status: StatusDoServico | None = None

    @field_validator("nome", "tipo_servico_id", "no_cnes", "status")
    @classmethod
    def _sem_nulo(cls, valor: object) -> object:
        # Roda só para o campo enviado; o ausente fica com o padrão e não é validado.
        if valor is None:
            raise ValueError("Campo obrigatório: não pode ser nulo.")
        return valor

    def alteracoes(self) -> dict[str, object]:
        """Coluna → valor, só dos campos enviados."""
        return {_COLUNA[campo]: getattr(self, campo) for campo in self.model_fields_set}


class ServicoOut(BaseModel):
    """O serviço; `unidade_id` nulo é o serviço solto (006/R6.2). `no_cnes` diz se ele consta no
    CNES (R6.3)."""

    id: UUID
    unidade_id: UUID | None
    equipamento_id: UUID | None
    nome: str
    tipo_servico_id: int
    no_cnes: bool
    status: str
    criado_em: datetime
    atualizado_em: datetime

    @classmethod
    def de(cls, servico: Servico) -> Self:
        return cls(
            id=servico.id,
            unidade_id=servico.unit_id,
            equipamento_id=servico.equipment_id,
            nome=servico.name,
            tipo_servico_id=servico.service_type_id,
            no_cnes=servico.in_cnes,
            status=servico.status,
            criado_em=servico.created_at,
            atualizado_em=servico.updated_at,
        )


_422 = problema(
    "Campos inválidos, tipo de serviço inexistente ou desativado, ou equipamento de outra unidade"
)


@router.get(
    "/unidades/{id}/servicos",
    summary="Listar serviços da unidade",
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
) -> list[ServicoOut]:
    """006/R6.1, R6.3: os serviços da unidade, pela ordem de cadastro, ligados a ela pelo id
    (R6.4)."""
    estado = request.app.state
    servicos = await listar_da_unidade(id, servicos=estado.repositorio_de_servicos(sessao))
    return [ServicoOut.de(s) for s in servicos]


@router.post(
    "/unidades/{id}/servicos",
    status_code=201,
    summary="Adicionar serviço à unidade",
    responses={
        401: problema("Sem access token válido"),
        403: problema("Sem `servico:write` no escopo da unidade"),
        404: problema("A unidade não existe"),
        422: _422,
    },
)
async def adicionar(
    request: Request,
    response: Response,
    id: UUID,
    corpo: ServicoCreate,
    usuario: Annotated[UsuarioAtual, Depends(require("servico:write", ResourceRef("unidade")))],
    sessao: SessaoDeNegocio,
) -> ServicoOut:
    """006/R6.1, R6.3: grava o serviço na unidade e audita `unidade.servico_criado`."""
    servico = await _adicionar(request, id, corpo, usuario, sessao)
    # A rota do serviço na unidade, a mesma do PATCH e do DELETE.
    response.headers["Location"] = f"/api/v1/unidades/{id}/servicos/{servico.id}"
    return ServicoOut.de(servico)


@router.patch(
    "/unidades/{id}/servicos/{sid}",
    summary="Alterar serviço da unidade",
    responses={
        401: problema("Sem access token válido"),
        403: problema("Sem `servico:write` no escopo da unidade"),
        404: problema("A unidade ou o serviço dela não existe"),
        422: _422,
    },
)
async def alterar(
    request: Request,
    id: UUID,
    sid: UUID,
    corpo: ServicoUpdate,
    usuario: Annotated[UsuarioAtual, Depends(require("servico:write", ResourceRef("unidade")))],
    sessao: SessaoDeNegocio,
) -> ServicoOut:
    """006/R6.1, R6.3: aplica só os campos enviados e audita `unidade.servico_atualizado` com o
    que mudou; sem mudança, responde igual, sem alterar nem auditar."""
    estado = request.app.state
    servico = await alterar_servico(
        id,
        sid,
        corpo.alteracoes(),
        ator=ator_da_requisicao(request, usuario),
        servicos=estado.repositorio_de_servicos(sessao),
        auditoria=estado.auditoria(sessao),
    )
    return ServicoOut.de(servico)


@router.delete(
    "/unidades/{id}/servicos/{sid}",
    status_code=204,
    summary="Remover serviço da unidade",
    responses={
        401: problema("Sem access token válido"),
        403: problema("Sem `servico:write` no escopo da unidade"),
        404: problema("A unidade ou o serviço dela não existe"),
    },
)
async def remover(
    request: Request,
    id: UUID,
    sid: UUID,
    usuario: Annotated[UsuarioAtual, Depends(require("servico:write", ResourceRef("unidade")))],
    sessao: SessaoDeNegocio,
) -> None:
    """006/R6.1: apaga o serviço e audita `unidade.servico_removido`."""
    estado = request.app.state
    await remover_servico(
        id,
        sid,
        ator=ator_da_requisicao(request, usuario),
        servicos=estado.repositorio_de_servicos(sessao),
        auditoria=estado.auditoria(sessao),
    )


@router.get(
    "/servicos",
    summary="Listar serviços soltos",
    responses={
        401: problema("Sem access token válido"),
        403: problema("Sem `servico:write` global"),
    },
)
async def listar_soltos_(
    request: Request,
    usuario: Annotated[UsuarioAtual, Depends(require("servico:write"))],
    sessao: SessaoDeNegocio,
) -> list[ServicoOut]:
    """006/R6.2: os serviços sem unidade, pela ordem de cadastro, só para o Gestor de Dados."""
    estado = request.app.state
    servicos = await listar_soltos(usuario=usuario, servicos=estado.repositorio_de_servicos(sessao))
    return [ServicoOut.de(s) for s in servicos]


@router.post(
    "/servicos",
    status_code=201,
    summary="Cadastrar serviço solto",
    responses={
        401: problema("Sem access token válido"),
        403: problema("Sem `servico:write` global"),
        422: problema(
            "Campos inválidos, tipo de serviço inexistente ou desativado, ou equipamento de uma"
            " unidade"
        ),
    },
)
async def adicionar_solto(
    request: Request,
    corpo: ServicoCreate,
    usuario: Annotated[UsuarioAtual, Depends(require("servico:write"))],
    sessao: SessaoDeNegocio,
) -> ServicoOut:
    """006/R6.2: grava o serviço sem unidade, como a Sala de Vacinação do Shopping, e audita
    `servico.criado`."""
    servico = await _adicionar(request, None, corpo, usuario, sessao)
    return ServicoOut.de(servico)


async def _adicionar(
    request: Request,
    unidade_id: UUID | None,
    corpo: ServicoCreate,
    usuario: UsuarioAtual,
    sessao: Any,
) -> Servico:
    estado = request.app.state
    return await adicionar_servico(
        unidade_id,
        corpo.dados(),
        novo_id=uuid7(),
        usuario=usuario,
        ator=ator_da_requisicao(request, usuario),
        servicos=estado.repositorio_de_servicos(sessao),
        auditoria=estado.auditoria(sessao),
    )
