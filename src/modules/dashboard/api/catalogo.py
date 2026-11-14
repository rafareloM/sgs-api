"""Rota do catálogo de consultas (spec 011, R3.1 e R3.2; design § Rotas).

`GET` de leitura com `require("dashboard:read")`; devolve só as consultas que o usuário pode
executar. Não lê o banco além da verificação de acesso.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from src.core.problem import PROBLEM_JSON
from src.modules.access.api.deps import UsuarioAtual, require
from src.modules.dashboard.api.schemas import ConsultaDescritaOut
from src.modules.dashboard.application import catalogo, consultas

_ERROS: dict[int | str, dict[str, Any]] = {
    401: {"description": "Sem access token válido", "content": {PROBLEM_JSON: {}}},
    403: {"description": "Sem `dashboard:read`", "content": {PROBLEM_JSON: {}}},
}

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"], responses=_ERROS)


@router.get("/consultas", summary="Catálogo das consultas que o usuário pode executar")
async def catalogo_de_consultas(
    usuario: Annotated[UsuarioAtual, Depends(require(consultas.PERMISSAO))],
) -> list[ConsultaDescritaOut]:
    """011/R3.1, R3.2: as consultas e views da 011 que o usuário tem permissão de executar."""
    return [
        ConsultaDescritaOut.model_validate(consulta)
        for consulta in catalogo.consultas_permitidas(usuario)
    ]
