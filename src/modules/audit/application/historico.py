"""Caso de uso do histórico da unidade (spec 008, R1; spec 011, R4.5; design da 011 § Rotas).

A rota exige `auditoria:read` no escopo da unidade pelo `require` da 003, que responde 403 fora
do escopo (008/R1.4) e 404 para unidade inexistente; aqui só se lê o histórico, pela porta
`HistoricoDeUnidades`, que consulta a `vw_unit_history`.
"""

from uuid import UUID

from src.modules.audit.domain.historico import (
    EventoDoHistorico,
    FiltrosDoHistorico,
    MudancaNoHistorico,
    Pagina,
    Resultado,
)
from src.modules.audit.domain.ports import HistoricoDeUnidades

# Reexportados para a camada api, que só importa a application.
__all__ = [
    "PERMISSAO",
    "EventoDoHistorico",
    "FiltrosDoHistorico",
    "HistoricoDeUnidades",
    "MudancaNoHistorico",
    "Pagina",
    "Resultado",
    "historico_da_unidade",
]

PERMISSAO = "auditoria:read"


async def historico_da_unidade(
    historico: HistoricoDeUnidades,
    unidade_id: UUID,
    filtros: FiltrosDoHistorico,
    pagina: Pagina,
) -> Resultado[EventoDoHistorico]:
    """008/R1.1, 008/R1.3, 011/R4.5: eventos da unidade, dos seus equipamentos e serviços, nos
    filtros pedidos, do mais recente ao mais antigo, paginados."""
    return await historico.eventos(unidade_id, filtros, pagina)
