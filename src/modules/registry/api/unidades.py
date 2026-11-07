"""Rotas da unidade de saúde (design da 006 § Rotas)."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response

from src.core.ids import uuid7
from src.core.problem import PROBLEM_JSON
from src.modules.access.api.deps import (
    SessaoDeNegocio,
    UsuarioAtual,
    ator_da_requisicao,
    require,
)
from src.modules.registry.api.schemas import UnidadeCreate, UnidadeOut
from src.modules.registry.application.unidades import criar_unidade

router = APIRouter(prefix="/api/v1", tags=["unidades"])


def _problema(descricao: str) -> dict[str, Any]:
    """Resposta de erro em problem+json (spec 001), para o contrato."""
    return {"description": descricao, "content": {PROBLEM_JSON: {}}}


@router.post(
    "/unidades",
    status_code=201,
    summary="Cadastrar unidade de saúde",
    responses={
        401: _problema("Sem access token válido"),
        403: _problema("Sem `unidade:create` na área técnica do tipo informado"),
        409: _problema("Já existe unidade com o mesmo CNES ou o mesmo nome no distrito"),
        422: _problema("Campos inválidos, ou tipo de unidade ou distrito inexistente"),
    },
)
async def criar(
    request: Request,
    response: Response,
    corpo: UnidadeCreate,
    usuario: Annotated[UsuarioAtual, Depends(require("unidade:create"))],
    sessao: SessaoDeNegocio,
) -> UnidadeOut:
    """006/R1. Responde com a unidade criada, o `Location` dela e o `ETag` da versão."""
    estado = request.app.state
    unidade = await criar_unidade(
        corpo.dados(),
        novo_id=uuid7(),
        usuario=usuario,
        ator=ator_da_requisicao(request, usuario),
        unidades=estado.repositorio_de_unidades(sessao),
        auditoria=estado.auditoria(sessao),
    )
    response.headers["Location"] = f"/api/v1/unidades/{unidade.id}"
    response.headers["ETag"] = f'"{unidade.version}"'
    return UnidadeOut.de(unidade)
