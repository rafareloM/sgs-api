"""Rotas do log do banco e das suas partições (spec 011, R6.9, R7.7 e R7.8; design § Rotas).

`GET` de leitura com `require("auditoria:read")`; o caso de uso exige ainda o escopo global
(011/R7.8) e levanta `AcessoNegado`, que a `SessaoDeNegocio` audita. Nada é gravado.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from pydantic import AwareDatetime

from src.core.paginacao import TAMANHO_PADRAO, NumeroDaPagina, PaginaOut, TamanhoDaPagina
from src.core.problem import problema
from src.modules.access.api.deps import SessaoDeNegocio, UsuarioAtual, require
from src.modules.audit.api.schemas import AlteracaoBancoOut, ParticaoOut
from src.modules.audit.application import log_banco
from src.modules.audit.application.log_banco import (
    FiltrosDoLog,
    LogDoBanco,
    Pagina,
    TabelaDoCadastro,
)


def _filtros(
    de: Annotated[
        AwareDatetime | None,
        Query(description="Início do período, incluído (data e hora com fuso)."),
    ] = None,
    ate: Annotated[
        AwareDatetime | None,
        Query(description="Fim do período, incluído (data e hora com fuso)."),
    ] = None,
    tabela: Annotated[
        TabelaDoCadastro | None, Query(description="Tabela do cadastro alterada.")
    ] = None,
    fora_da_api: Annotated[
        bool | None,
        Query(
            description=(
                "Verdadeiro: só alterações feitas fora da API; falso: só as feitas pela API."
            )
        ),
    ] = None,
) -> FiltrosDoLog:
    """Filtros por período, tabela e origem (011/R7.7)."""
    return FiltrosDoLog(de=de, ate=ate, tabela=tabela, fora_da_api=fora_da_api)


router = APIRouter(
    prefix="/api/v1/auditoria/banco",
    tags=["auditoria"],
    responses={
        401: problema("Sem access token válido"),
        403: problema("Sem `auditoria:read` em escopo global"),
    },
)

Auditor = Annotated[UsuarioAtual, Depends(require(log_banco.PERMISSAO))]


@router.get(
    "",
    summary="Log do banco: alterações do cadastro registradas pelo PostgreSQL",
    responses={422: problema("Filtro ou paginação mal formados")},
)
async def listar(
    request: Request,
    usuario: Auditor,
    sessao: SessaoDeNegocio,
    filtros: Annotated[FiltrosDoLog, Depends(_filtros)],
    pagina: NumeroDaPagina = 1,
    tamanho: TamanhoDaPagina = TAMANHO_PADRAO,
) -> PaginaOut[AlteracaoBancoOut]:
    """011/R7.7: registros do log nos filtros pedidos, do mais recente para o mais antigo,
    paginados."""
    porta: LogDoBanco = request.app.state.log_do_banco(sessao)
    pedida = Pagina(numero=pagina, tamanho=tamanho)
    resultado = await log_banco.listar_alteracoes(porta, usuario, filtros, pedida)
    return PaginaOut(
        itens=[AlteracaoBancoOut.model_validate(item) for item in resultado.itens],
        total=resultado.total,
        pagina=pagina,
        tamanho=tamanho,
    )


@router.get("/particoes", summary="Partições do log do banco, com intervalo e registros")
async def particoes(
    request: Request, usuario: Auditor, sessao: SessaoDeNegocio
) -> list[ParticaoOut]:
    """011/R6.9: cada partição com o intervalo (`de` incluído, `ate` excluído; nulos na
    DEFAULT) e a quantidade de registros."""
    porta: LogDoBanco = request.app.state.log_do_banco(sessao)
    return [
        ParticaoOut.model_validate(particao)
        for particao in await log_banco.listar_particoes(porta, usuario)
    ]
