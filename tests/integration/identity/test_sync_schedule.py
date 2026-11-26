"""Agendamento da sincronização (004/T9; design § Agendamento; R1.12).

Relógio e espera falsos: nenhum teste dorme de verdade.
"""

import asyncio
import logging
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import text

from src.core.config import SettingsError
from src.core.ids import uuid7
from src.main import create_app
from src.modules.identity.application.agendamento import agendar, sincronizar_agendada
from src.modules.identity.application.sincronizacao import iniciar_sincronizacao
from src.modules.identity.domain.cron import analisar
from src.modules.identity.domain.diretorio import (
    DirectoryGroup,
    DirectorySnapshot,
    DirectoryUser,
)
from tests.factories import make_settings
from tests.integration.acesso import Sessoes
from tests.integration.identity.sincronizacao import transacoes_de
from tests.integration.postgres import BancoDeTeste

RECIFE = timezone(timedelta(hours=-3), "America/Recife")
AGORA = datetime(2026, 11, 26, 12, 0, tzinfo=UTC)


class DiretorioFalso:
    async def snapshot(self) -> DirectorySnapshot:
        ana = DirectoryUser(
            external_id="uuid-ana", dn="uid=ana", login="ana", email=None, display_name="Ana"
        )
        return DirectorySnapshot(users=(ana,), groups=())

    async def find_user(self, login: str) -> DirectoryUser | None:  # pragma: no cover
        raise NotImplementedError

    async def verify_password(self, dn: str, password: str) -> bool:  # pragma: no cover
        raise NotImplementedError

    async def groups_of(
        self, user: DirectoryUser
    ) -> tuple[DirectoryGroup, ...]:  # pragma: no cover
        raise NotImplementedError


class _Parar(Exception):  # noqa: N818 - sinal de parada do teste
    """Interrompe o laço do agendador no teste."""


class RelogioFalso:
    """Relógio de Recife que a espera falsa adianta; para depois de `limite` esperas."""

    def __init__(self, inicio: datetime, limite: int) -> None:
        self.agora = inicio
        self.esperas: list[float] = []
        self._limite = limite

    def __call__(self) -> datetime:
        return self.agora

    async def esperar(self, segundos: float) -> None:
        if len(self.esperas) == self._limite:
            raise _Parar
        self.esperas.append(segundos)
        self.agora += timedelta(seconds=segundos)


@pytest.fixture
def log_do_diretorio(caplog: pytest.LogCaptureFixture) -> Iterator[pytest.LogCaptureFixture]:
    """O log `sgs_api.diretorio`, com o handler preso ao próprio logger e o logger ligado. Outros
    testes mexem no logging do processo: o `configure_logging` troca os handlers da raiz, e o
    import-linter (`tests/architecture/test_camadas.py`), rodando no mesmo processo, desativa os
    loggers que já existem."""
    log = logging.getLogger("sgs_api.diretorio")
    nivel, desativado = log.level, log.disabled
    log.addHandler(caplog.handler)
    log.setLevel(logging.INFO)
    log.disabled = False
    try:
        yield caplog
    finally:
        log.removeHandler(caplog.handler)
        log.setLevel(nivel)
        log.disabled = desativado


async def _execucoes(sessoes: Sessoes) -> list[dict[str, Any]]:
    async with sessoes() as sessao:
        resultado = await sessao.execute(
            text("SELECT status, triggered_by FROM directory_sync_runs ORDER BY started_at")
        )
        return [dict(linha) for linha in resultado.mappings()]


async def test_agendada_roda_com_ator_sistema_e_origem_agendador(sessoes: Sessoes) -> None:
    """004/R1.12 (design § Agendamento: o mesmo caso de uso, ator `sistema`, origem
    `agendador`)"""
    rodou = await sincronizar_agendada(
        diretorio=DiretorioFalso(),
        transacoes=transacoes_de(sessoes),
        gerar_id=uuid7,
        agora=lambda: AGORA,
    )

    assert rodou is True
    assert await _execucoes(sessoes) == [{"status": "concluida", "triggered_by": None}]
    async with sessoes() as sessao:
        ator = (
            await sessao.execute(
                text(
                    "SELECT actor_type, origin, actor_user_id FROM audit_log"
                    " WHERE action = 'diretorio.sincronizado'"
                )
            )
        ).one()
    assert tuple(ator) == ("sistema", "agendador", None)


async def test_agendada_pula_se_ja_houver_execucao_em_andamento(
    sessoes: Sessoes, log_do_diretorio: pytest.LogCaptureFixture
) -> None:
    """004/R1.11, R1.12 (registra no log e pula)"""
    transacoes = transacoes_de(sessoes)
    await iniciar_sincronizacao(
        uuid7(), triggered_by=None, transacoes=transacoes, agora=lambda: AGORA
    )

    rodou = await sincronizar_agendada(
        diretorio=DiretorioFalso(), transacoes=transacoes, gerar_id=uuid7, agora=lambda: AGORA
    )

    assert rodou is False
    assert [e["status"] for e in await _execucoes(sessoes)] == ["em_andamento"]
    assert "pulada" in log_do_diretorio.text


async def test_laco_espera_ate_cada_horario_no_fuso_de_recife() -> None:
    """004/R1.12 (`30 2 * * *` às 2h30 de Recife, uma vez por dia)"""
    relogio = RelogioFalso(datetime(2026, 11, 26, 1, 0, tzinfo=RECIFE), limite=2)
    horarios: list[datetime] = []

    async def rodar() -> None:
        horarios.append(relogio())

    with pytest.raises(_Parar):
        await agendar(analisar("30 2 * * *"), relogio=relogio, esperar=relogio.esperar, rodar=rodar)

    assert relogio.esperas == [90 * 60, 24 * 3600]
    assert horarios == [
        datetime(2026, 11, 26, 2, 30, tzinfo=RECIFE),
        datetime(2026, 11, 27, 2, 30, tzinfo=RECIFE),
    ]


async def test_falha_numa_execucao_nao_para_o_laco(
    log_do_diretorio: pytest.LogCaptureFixture,
) -> None:
    """004/R1.12"""
    relogio = RelogioFalso(datetime(2026, 11, 26, 1, 0, tzinfo=RECIFE), limite=3)
    chamadas = 0

    async def rodar() -> None:
        nonlocal chamadas
        chamadas += 1
        raise RuntimeError("banco fora")

    with pytest.raises(_Parar):
        await agendar(analisar("0 * * * *"), relogio=relogio, esperar=relogio.esperar, rodar=rodar)

    assert chamadas == 3
    assert "RuntimeError" in log_do_diretorio.text
    assert "banco fora" not in log_do_diretorio.text  # só o tipo do erro vai para o log


def _settings_com_ldap(banco: BancoDeTeste, tmp_path: Path, **extra: Any) -> Any:
    ca = tmp_path / "ca.crt"
    ca.write_text("-----BEGIN CERTIFICATE-----\n", encoding="utf-8")
    return make_settings(
        database_url=SecretStr(banco.url_api),
        ldap_url="ldaps://ldap:636",
        ldap_ca_file=str(ca),
        ldap_bind_dn="cn=sgs-sync,dc=recife",
        ldap_bind_password=SecretStr("senha-de-teste"),
        ldap_user_base="ou=pessoas,dc=recife",
        ldap_user_filter="(objectClass=inetOrgPerson)",
        ldap_group_base="ou=grupos,dc=recife",
        ldap_group_filter="(objectClass=groupOfNames)",
        **extra,
    )


async def test_lifespan_inicia_o_agendador_e_o_cancela_no_desligamento(
    banco: BancoDeTeste, tmp_path: Path
) -> None:
    """004/R1.12 (tarefa `asyncio` no lifespan, cancelada no desligamento)"""
    app = create_app(_settings_com_ldap(banco, tmp_path, ldap_sync_cron="30 2 * * *"))

    async with app.router.lifespan_context(app):
        tarefa: asyncio.Task[None] = app.state.agendador_do_diretorio
        assert tarefa is not None
        assert not tarefa.done()

    assert tarefa.cancelled()


async def test_sem_cron_nao_ha_agendador(banco: BancoDeTeste, tmp_path: Path) -> None:
    """004/R1.12 (ONDE `LDAP_SYNC_CRON` estiver configurado)"""
    app = create_app(_settings_com_ldap(banco, tmp_path))

    async with app.router.lifespan_context(app):
        assert app.state.agendador_do_diretorio is None


def test_cron_fora_do_subconjunto_recusa_a_subida(banco: BancoDeTeste, tmp_path: Path) -> None:
    """004/R1.12; D004-9 (recusada na subida com mensagem clara)"""
    with pytest.raises(SettingsError, match="LDAP_SYNC_CRON: dia, mês e dia da semana"):
        create_app(_settings_com_ldap(banco, tmp_path, ldap_sync_cron="30 2 * * 1"))


async def test_acordar_um_pouco_antes_nao_dispara_duas_vezes_o_mesmo_horario() -> None:
    """004/R1.12 (a espera é monotônica e o relógio é de parede: o próximo horário parte do
    horário que acabou de disparar)"""
    relogio = RelogioFalso(datetime(2026, 11, 26, 2, 0, tzinfo=RECIFE), limite=2)
    original = relogio.esperar

    async def acorda_cedo(segundos: float) -> None:
        await original(segundos)
        relogio.agora -= timedelta(milliseconds=2)

    horarios: list[datetime] = []

    async def rodar() -> None:
        horarios.append(relogio())

    with pytest.raises(_Parar):
        await agendar(analisar("30 2 * * *"), relogio=relogio, esperar=acorda_cedo, rodar=rodar)

    assert [h.date().day for h in horarios] == [26, 27]
