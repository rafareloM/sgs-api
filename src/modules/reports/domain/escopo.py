"""Escopo gravado no pedido e comparação de escopos (spec 005, design § Escopo dos relatórios;
R1.3, R3.3).

O pedido grava o `EscopoLeitura` de quem pediu, na permissão de dados do tipo (`scope_snapshot`),
e a geração usa só ele (R1.3). Outra pessoa baixa o relatório se, na mesma permissão de dados,
tiver um escopo que cubra o gravado (R3.3): `escopo_cobre`.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


class Escopo(Protocol):
    """O que se lê de um escopo: o `EscopoLeitura` do módulo de acesso ou o `EscopoGravado`."""

    @property
    def global_(self) -> bool: ...

    @property
    def areas(self) -> Sequence[int]: ...

    @property
    def distritos(self) -> Sequence[int]: ...

    @property
    def unidades(self) -> Sequence[UUID]: ...


@dataclass(frozen=True, slots=True)
class EscopoGravado:
    """Escopo de leitura de quem pediu, como o pedido o guarda (R1.3)."""

    global_: bool = False
    areas: tuple[int, ...] = ()
    distritos: tuple[int, ...] = ()
    unidades: tuple[UUID, ...] = ()


def escopo_cobre(maior: Escopo, menor: Escopo) -> bool:
    """R3.3: se o escopo `maior` (de quem baixa) é igual ou maior que o `menor` (o gravado).

    - Global cobre tudo; só global cobre global.
    - Senão, cada conjunto do gravado (áreas, distritos, unidades) tem de estar contido no
      conjunto do mesmo nível de quem baixa. A comparação é conservadora: um distrito não cobre
      unidades, mesmo que fiquem nele, porque saber isso exigiria consultar o banco.
    - Escopo vazio não cobre nada (deny by default): é o que `escopo_de_leitura` devolve para
      quem não tem a permissão de dados. E um gravado vazio só é coberto pelo global: a conta
      "vazio está contido em tudo" não libera download (pedir exige a permissão de dados, então
      um pedido não deveria ter escopo vazio).
    """
    if maior.global_:
        return True
    if menor.global_ or _vazio(maior) or _vazio(menor):
        return False
    return (
        set(menor.areas) <= set(maior.areas)
        and set(menor.distritos) <= set(maior.distritos)
        and set(menor.unidades) <= set(maior.unidades)
    )


def _vazio(escopo: Escopo) -> bool:
    return not (escopo.global_ or escopo.areas or escopo.distritos or escopo.unidades)
