"""Rota do histórico da unidade (spec 008, R1, adiantada pela 011, R4.5; design da 011 § Rotas).

`GET` de leitura com `require("auditoria:read", ResourceRef("unidade"))`: sem token, 401; sem a
permissão, ou com ela fora do escopo da unidade, 403 (008/R1.4); unidade inexistente, 404 a quem
tem a permissão. A sessão é só de leitura: nada é gravado.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import AwareDatetime

from src.core.paginacao import TAMANHO_PADRAO, NumeroDaPagina, PaginaOut, TamanhoDaPagina
from src.core.problem import problema
from src.modules.access.api.deps import ResourceRef, require
from src.modules.audit.api.schemas import EventoHistoricoOut
from src.modules.audit.application import historico
from src.modules.audit.application.historico import (
    FiltrosDoHistorico,
    HistoricoDeUnidades,
    Pagina,
)

# Tamanho de `changes[].campo` aceito no filtro: nomes de coluna e caminhos como
# `equipamento.nome` cabem com folga.
_CAMPO_MAXIMO = 100


def _filtros(
    de: Annotated[
        AwareDatetime | None,
        Query(description="Início do período, incluído (data e hora com fuso)."),
    ] = None,
    ate: Annotated[
        AwareDatetime | None,
        Query(description="Fim do período, incluído (data e hora com fuso)."),
    ] = None,
    autor: Annotated[UUID | None, Query(description="Id do usuário autor do evento.")] = None,
    campo: Annotated[
        str | None,
        Query(
            min_length=1,
            max_length=_CAMPO_MAXIMO,
            description="Nome do campo alterado, como gravado na lista {campo, de, para}.",
        ),
    ] = None,
) -> FiltrosDoHistorico:
    """Filtros por período, autor e campo (008/R1.3)."""
    return FiltrosDoHistorico(de=de, ate=ate, autor=autor, campo=campo)


router = APIRouter(prefix="/api/v1", tags=["auditoria"])


@router.get(
    "/unidades/{id}/historico",
    summary="Histórico de alterações da unidade",
    dependencies=[Depends(require(historico.PERMISSAO, ResourceRef("unidade")))],
    responses={
        401: problema("Sem access token válido"),
        403: problema("Sem `auditoria:read` no escopo da unidade"),
        404: problema("Unidade inexistente"),
        422: problema("Filtro ou paginação mal formados"),
    },
)
async def historico_da_unidade(
    request: Request,
    id: UUID,
    filtros: Annotated[FiltrosDoHistorico, Depends(_filtros)],
    pagina: NumeroDaPagina = 1,
    tamanho: TamanhoDaPagina = TAMANHO_PADRAO,
) -> PaginaOut[EventoHistoricoOut]:
    """008/R1.1, 008/R1.3, 011/R4.5: eventos da unidade e dos seus equipamentos e serviços,
    lidos da `vw_unit_history`, nos filtros pedidos, do mais recente ao mais antigo."""
    pedida = Pagina(numero=pagina, tamanho=tamanho)
    async with request.app.state.sessoes() as sessao:
        porta: HistoricoDeUnidades = request.app.state.historico_de_unidades(sessao)
        resultado = await historico.historico_da_unidade(porta, id, filtros, pedida)
    return PaginaOut(
        itens=[EventoHistoricoOut.model_validate(evento) for evento in resultado.itens],
        total=resultado.total,
        pagina=pagina,
        tamanho=tamanho,
    )
