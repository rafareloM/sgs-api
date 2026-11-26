"""Agendamento da sincronização do diretório (spec 004, T9; design § Agendamento; R1.12).

`agendar` calcula o próximo horário da agenda no fuso do relógio dado (Recife, pela raiz de
composição), espera até ele e dispara a sincronização pelo mesmo caso de uso da rota, com o ator
`sistema` e a origem `agendador`. Se já houver execução em andamento, registra no log e pula.
Roda até ser cancelada (no desligamento da API).
"""

import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from uuid import UUID

from src.modules.audit.application.registrar import Ator
from src.modules.identity.application.sincronizacao import (
    Transacoes,
    iniciar_sincronizacao,
    sincronizar,
)
from src.modules.identity.domain.cron import Agenda
from src.modules.identity.domain.diretorio import DirectoryPort

ATOR_DO_AGENDADOR = Ator(tipo="sistema", origem="agendador")

_log = logging.getLogger("sgs_api.diretorio")


async def sincronizar_agendada(
    *,
    diretorio: DirectoryPort,
    transacoes: Transacoes,
    gerar_id: Callable[[], UUID],
    agora: Callable[[], datetime],
) -> bool:
    """Uma execução agendada (`triggered_by` nulo); `False` se pulou por já haver outra."""
    execucao_id = gerar_id()
    if not await iniciar_sincronizacao(
        execucao_id, triggered_by=None, transacoes=transacoes, agora=agora
    ):
        _log.info("sincronização agendada pulada: já há uma execução em andamento")
        return False
    await sincronizar(
        execucao_id,
        diretorio=diretorio,
        transacoes=transacoes,
        ator=ATOR_DO_AGENDADOR,
        gerar_id=gerar_id,
        agora=agora,
    )
    return True


async def agendar(
    agenda: Agenda,
    *,
    relogio: Callable[[], datetime],
    esperar: Callable[[float], Awaitable[None]],
    rodar: Callable[[], Awaitable[object]],
) -> None:
    """Laço do agendador. Uma falha numa execução vai para o log e não para o laço."""
    referencia = relogio()
    while True:
        proximo = agenda.proximo(referencia)
        await esperar(max((proximo - relogio()).total_seconds(), 0.0))
        try:
            await rodar()
        except Exception as erro:
            _log.error("sincronização agendada falhou ao iniciar: %s", type(erro).__name__)
        # A espera é monotônica e o relógio é de parede: acordar um pouco antes não pode
        # disparar o mesmo horário de novo.
        referencia = max(relogio(), proximo)
