"""Escopo gravado no pedido e comparação de escopos (spec 005, design § Escopo dos relatórios;
R1.3, R3.3).

O pedido grava o `EscopoLeitura` de quem pediu, na permissão de dados do tipo (`scope_snapshot`),
e a geração usa só ele (R1.3). Outra pessoa baixa o relatório se, na mesma permissão de dados,
tiver um escopo que cubra o gravado (R3.3): `escopo_cobre`.
"""

from collections.abc import Mapping, Sequence
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


def escopo_para_gravar(escopo: Escopo) -> dict[str, object]:
    """O `scope_snapshot` do pedido, em JSON: `global_` vira `global`, os UUIDs viram texto."""
    return {
        "global": bool(escopo.global_),
        "areas": sorted(int(area) for area in escopo.areas),
        "distritos": sorted(int(distrito) for distrito in escopo.distritos),
        "unidades": sorted(str(unidade) for unidade in escopo.unidades),
    }


def escopo_gravado(snapshot: Mapping[str, object]) -> EscopoGravado:
    """O `scope_snapshot` lido de volta. Um snapshot fora do formato levanta `ValueError`, e o
    pedido falha fechado, em vez de virar um escopo maior ou menor que o gravado."""
    if set(snapshot) != {"global", "areas", "distritos", "unidades"}:
        raise ValueError("escopo gravado fora do formato")
    global_ = snapshot["global"]
    areas, distritos, unidades = (
        _lista(snapshot["areas"]),
        _lista(snapshot["distritos"]),
        _lista(snapshot["unidades"]),
    )
    if not isinstance(global_, bool) or not all(type(i) is int for i in (*areas, *distritos)):
        raise ValueError("escopo gravado fora do formato")
    if not all(isinstance(unidade, str) for unidade in unidades):
        raise ValueError("escopo gravado fora do formato")
    try:
        ids_de_unidade = tuple(UUID(str(unidade)) for unidade in unidades)
    except ValueError:
        raise ValueError("escopo gravado fora do formato") from None
    return EscopoGravado(
        global_=global_,
        areas=tuple(area for area in areas if isinstance(area, int)),
        distritos=tuple(distrito for distrito in distritos if isinstance(distrito, int)),
        unidades=ids_de_unidade,
    )


def _lista(valor: object) -> list[object]:
    if not isinstance(valor, list):
        raise ValueError("escopo gravado fora do formato")
    return valor
