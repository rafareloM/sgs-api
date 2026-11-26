"""Subconjunto de cron do agendamento da sincronização (spec 004, T9; design § Agendamento).

Cinco campos. Minuto e hora aceitam número, `*`, `*/n` e lista `a,b`; dia, mês e dia da semana
só `*` (D004-9). Qualquer outra forma é recusada, para nada ser aceito calado com um sentido
diferente do esperado. Só stdlib: o fuso é o do instante que quem chama passa (Recife, pela raiz
de composição).
"""

from dataclasses import dataclass
from datetime import datetime, timedelta


class CronInvalido(ValueError):  # noqa: N818 - nome em português, como DirectoryUnavailable
    """A expressão está fora do subconjunto aceito; a mensagem diz o que corrigir."""


@dataclass(frozen=True)
class Agenda:
    minutos: tuple[int, ...]  # em ordem
    horas: tuple[int, ...]  # em ordem

    def proximo(self, depois_de: datetime) -> datetime:
        """O primeiro horário da agenda estritamente depois de `depois_de`, no mesmo fuso."""
        base = depois_de.replace(second=0, microsecond=0)
        for dias in (0, 1):  # dia, mês e dia da semana são `*`: o próximo está em até 24 h
            dia = base + timedelta(days=dias)
            for hora in self.horas:
                for minuto in self.minutos:
                    candidato = dia.replace(hour=hora, minute=minuto)
                    if candidato > depois_de:
                        return candidato
        raise AssertionError("inalcançável: há ao menos um horário por dia")  # pragma: no cover


def analisar(expressao: str) -> Agenda:
    campos = expressao.split()
    if len(campos) != 5:
        raise CronInvalido("use cinco campos: minuto hora dia mês dia-da-semana")
    minuto, hora, *resto = campos
    if any(campo != "*" for campo in resto):
        raise CronInvalido("dia, mês e dia da semana aceitam só *")
    return Agenda(minutos=_campo(minuto, "minuto", 59), horas=_campo(hora, "hora", 23))


def _campo(texto: str, nome: str, maximo: int) -> tuple[int, ...]:
    if texto == "*":
        return tuple(range(maximo + 1))
    if texto.startswith("*/"):
        passo = _numero(texto[2:], nome, 1, maximo)
        return tuple(range(0, maximo + 1, passo))
    valores = {_numero(parte, nome, 0, maximo) for parte in texto.split(",")}
    return tuple(sorted(valores))


def _numero(texto: str, nome: str, minimo: int, maximo: int) -> int:
    if not texto.isascii() or not texto.isdigit():
        raise CronInvalido(f"{nome}: use número, *, */n ou lista a,b")
    valor = int(texto)
    if not minimo <= valor <= maximo:
        raise CronInvalido(f"{nome}: use de {minimo} a {maximo}")
    return valor
