"""Subconjunto de cron do agendamento da sincronização (004/T9; design § Agendamento)."""

from datetime import datetime, timedelta, timezone

import pytest

from src.modules.identity.domain.cron import CronInvalido, analisar

RECIFE = timezone(timedelta(hours=-3), "America/Recife")


def _em(dia: int, hora: int, minuto: int, segundo: int = 0) -> datetime:
    return datetime(2026, 11, dia, hora, minuto, segundo, tzinfo=RECIFE)


@pytest.mark.parametrize(
    ("expressao", "agora", "esperado"),
    [
        ("30 2 * * *", _em(26, 1, 0), _em(26, 2, 30)),
        ("30 2 * * *", _em(26, 2, 30), _em(27, 2, 30)),  # estritamente depois
        ("30 2 * * *", _em(26, 2, 29, 59), _em(26, 2, 30)),
        ("0 */6 * * *", _em(26, 7, 15), _em(26, 12, 0)),
        ("*/15 * * * *", _em(26, 23, 50), _em(27, 0, 0)),
        ("0,30 8,18 * * *", _em(26, 8, 10), _em(26, 8, 30)),
        ("0,30 8,18 * * *", _em(26, 18, 45), _em(27, 8, 0)),
        ("* * * * *", _em(26, 10, 0, 1), _em(26, 10, 1)),
    ],
)
def test_proximo_horario_no_fuso_de_quem_pergunta(
    expressao: str, agora: datetime, esperado: datetime
) -> None:
    """004/R1.12"""
    proximo = analisar(expressao).proximo(agora)

    assert proximo == esperado
    assert proximo.tzinfo is agora.tzinfo


def test_virada_de_mes_e_de_ano() -> None:
    """004/R1.12"""
    agenda = analisar("30 2 * * *")
    virada = datetime(2026, 12, 31, 3, 0, tzinfo=RECIFE)

    assert agenda.proximo(virada) == datetime(2027, 1, 1, 2, 30, tzinfo=RECIFE)


@pytest.mark.parametrize(
    "expressao",
    [
        "",
        "30 2 * *",
        "30 2 * * * *",
        "60 2 * * *",
        "30 24 * * *",
        "-1 2 * * *",
        "*/0 2 * * *",
        "*/61 * * * *",
        "30 2 1 * *",
        "30 2 * 1 *",
        "30 2 * * 1",
        "30 2 * * MON",
        "1-5 2 * * *",
        "30, * * * *",
        "a 2 * * *",
        "@daily",
    ],
)
def test_formas_fora_do_subconjunto_sao_recusadas(expressao: str) -> None:
    """004/R1.12; D004-9 (mensagem clara, sem aceitar calado o que não entende)"""
    with pytest.raises(CronInvalido) as erro:
        analisar(expressao)

    assert str(erro.value)
