"""Paginação das listagens da API (design da 006 § Schemas; 006/R2.1).

`PaginaOut[T]` é a resposta de toda listagem paginada (`itens`, `total`, `pagina`, `tamanho`).
`NumeroDaPagina` e `TamanhoDaPagina` são os parâmetros `pagina` e `tamanho` da query string:
padrão 20 itens, máximo 100. Paginação por offset: o volume do cadastro (~250 a 1.000 unidades)
não justifica cursor.

    async def listar(pagina: NumeroDaPagina = 1, tamanho: TamanhoDaPagina = TAMANHO_PADRAO): ...
"""

from typing import Annotated

from fastapi import Query
from pydantic import BaseModel

TAMANHO_PADRAO = 20
TAMANHO_MAXIMO = 100

NumeroDaPagina = Annotated[int, Query(ge=1, le=1_000_000, description="Página, a partir de 1.")]
TamanhoDaPagina = Annotated[
    int, Query(ge=1, le=TAMANHO_MAXIMO, description="Itens por página (padrão 20, máximo 100).")
]


class PaginaOut[T](BaseModel):
    """Uma página de uma listagem e o total de itens da listagem inteira."""

    itens: list[T]
    total: int
    pagina: int
    tamanho: int
