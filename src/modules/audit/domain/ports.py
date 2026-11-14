"""Portas do módulo de auditoria."""

from typing import Protocol
from uuid import UUID

from src.modules.audit.domain.entry import AuditEntry
from src.modules.audit.domain.historico import (
    EventoDoHistorico,
    FiltrosDoHistorico,
    Pagina,
    Resultado,
)
from src.modules.audit.domain.log_banco import AlteracaoBanco, FiltrosDoLog, ParticaoDoLog


class AuditStore(Protocol):
    """Armazenamento da trilha, preso à transação do caso de uso que registra o evento."""

    async def lock_chain_head(self) -> str:
        """Trava a cabeça da cadeia até o fim da transação e devolve o hash do último registro."""
        ...

    async def append(self, entry: AuditEntry) -> None:
        """Insere o registro e move a cabeça da cadeia para o hash dele."""
        ...


class HistoricoDeUnidades(Protocol):
    """Leitura do histórico de uma unidade pela `vw_unit_history` (spec 011, R4.5), sobre a
    sessão de quem a usa, só para leitura."""

    async def eventos(
        self, unidade_id: UUID, filtros: FiltrosDoHistorico, pagina: Pagina
    ) -> Resultado[EventoDoHistorico]:
        """Eventos da unidade e dos seus equipamentos e serviços que passam nos filtros
        (008/R1.3), do mais recente ao mais antigo (008/R1.1)."""
        ...


class LogDoBanco(Protocol):
    """Leitura do log do banco (`db_change_log`, 011/R7) sobre a sessão de quem o consulta; a
    aplicação só lê o log (011/R7.6)."""

    async def listar(self, filtros: FiltrosDoLog, pagina: Pagina) -> Resultado[AlteracaoBanco]:
        """Registros do log que passam nos filtros, do mais recente para o mais antigo
        (011/R7.7)."""
        ...

    async def particoes(self) -> tuple[ParticaoDoLog, ...]:
        """Partições do log com o intervalo e a quantidade de registros (011/R6.9)."""
        ...
