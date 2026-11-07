"""Rotas das consultas de qualidade do cadastro (spec 011, R2; design § Rotas).

Todas são `GET` de leitura com `require("dashboard:read")` (011/R2.8), e cada consulta aplica o
escopo de leitura do usuário (011/R2.5). A sessão é só de leitura: nada é gravado.
"""

from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request

from src.core.paginacao import TAMANHO_PADRAO, NumeroDaPagina, PaginaOut, TamanhoDaPagina
from src.core.problem import PROBLEM_JSON
from src.modules.access.api.deps import UsuarioAtual, require
from src.modules.dashboard.api.schemas import ConciliacaoOut, UnidadeResumoOut
from src.modules.dashboard.application import consultas
from src.modules.dashboard.application.consultas import ConsultasDashboard, Filtros, Pagina

_ERROS: dict[int | str, dict[str, Any]] = {
    401: {"description": "Sem access token válido", "content": {PROBLEM_JSON: {}}},
    403: {"description": "Sem `dashboard:read`", "content": {PROBLEM_JSON: {}}},
    422: {
        "description": "Filtro mal formado, ou distrito ou tipo inexistente",
        "content": {PROBLEM_JSON: {}},
    },
}

router = APIRouter(prefix="/api/v1/dashboard/consultas", tags=["dashboard"], responses=_ERROS)

Leitor = Annotated[UsuarioAtual, Depends(require(consultas.PERMISSAO))]

# Ids de referência são `smallint` no banco: o limite barra no 422 o que não caberia (011/R2.9).
_ID_DE_REFERENCIA_MAXIMO = 32767


@dataclass(frozen=True, slots=True)
class _Pedido:
    filtros: Filtros
    pagina: Pagina


def _pedido(
    distrito: Annotated[
        int | None,
        Query(ge=1, le=_ID_DE_REFERENCIA_MAXIMO, description="Id do distrito sanitário."),
    ] = None,
    tipo: Annotated[
        int | None,
        Query(ge=1, le=_ID_DE_REFERENCIA_MAXIMO, description="Id do tipo de unidade."),
    ] = None,
    pagina: NumeroDaPagina = 1,
    tamanho: TamanhoDaPagina = TAMANHO_PADRAO,
) -> _Pedido:
    """Filtros de distrito e de tipo de unidade (011/R2.7) e a página pedida."""
    return _Pedido(Filtros(distrito=distrito, tipo=tipo), Pagina(numero=pagina, tamanho=tamanho))


Pedido = Annotated[_Pedido, Depends(_pedido)]


@router.get(
    "/unidades-sem-servico",
    summary="Unidades sem nenhum serviço cadastrado (anti join)",
)
async def unidades_sem_servico(
    request: Request, usuario: Leitor, pedido: Pedido
) -> PaginaOut[UnidadeResumoOut]:
    """011/R2.1: unidades não inativas sem serviço, no escopo de leitura do usuário."""
    async with request.app.state.sessoes() as sessao:
        porta: ConsultasDashboard = request.app.state.consultas_dashboard(sessao)
        resultado = await consultas.unidades_sem_servico(
            porta, usuario, pedido.filtros, pedido.pagina
        )
    return PaginaOut(
        itens=[UnidadeResumoOut.model_validate(item) for item in resultado.itens],
        total=resultado.total,
        pagina=pedido.pagina.numero,
        tamanho=pedido.pagina.tamanho,
    )


@router.get(
    "/conciliacao-unidade-equipamento",
    summary="Conciliação unidade x equipamento (full outer join)",
)
async def conciliacao_unidade_equipamento(
    request: Request, usuario: Leitor, pedido: Pedido
) -> PaginaOut[ConciliacaoOut]:
    """011/R2.2, R2.6: pares, unidades sem equipamento e, só com escopo global e sem filtro,
    equipamentos sem unidade."""
    async with request.app.state.sessoes() as sessao:
        porta: ConsultasDashboard = request.app.state.consultas_dashboard(sessao)
        resultado = await consultas.conciliacao_unidade_equipamento(
            porta, usuario, pedido.filtros, pedido.pagina
        )
    return PaginaOut(
        itens=[ConciliacaoOut.model_validate(item) for item in resultado.itens],
        total=resultado.total,
        pagina=pedido.pagina.numero,
        tamanho=pedido.pagina.tamanho,
    )
