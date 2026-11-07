"""Escopos e verificação de permissão (spec 003, design § Resolução de permissões e § Verificação).

Funções puras, sem banco: `permissoes_efetivas` monta as permissões a partir das concessões já
lidas, e `pode` verifica uma permissão contra os atributos de escopo do recurso.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from uuid import UUID


@dataclass(frozen=True, slots=True)
class Global:
    """Vale para qualquer recurso."""


@dataclass(frozen=True, slots=True)
class Area:
    """Uma área técnica (`technical_areas.id`)."""

    id: int


@dataclass(frozen=True, slots=True)
class Distrito:
    """Um distrito sanitário (`districts.id`)."""

    id: int


@dataclass(frozen=True, slots=True)
class Unidade:
    """Uma unidade de saúde (`health_units.id`)."""

    id: UUID


type Escopo = Global | Area | Distrito | Unidade

type PermissoesEfetivas = Mapping[str, Sequence[Escopo]]
"""Código da permissão (`recurso:acao`) → escopos em que o usuário a tem."""


def escopo_de(nivel: str, id_do_escopo: str | None) -> Escopo:
    """Escopo de uma atribuição a partir de `scope_type` e `scope_id` (texto; nulo se global).

    Dado mal formado levanta `ValueError`: falha em vez de conceder.
    """
    try:
        match nivel, id_do_escopo:
            case "global", None:
                return Global()
            case "area", str(texto):
                return Area(int(texto))
            case "distrito", str(texto):
                return Distrito(int(texto))
            case "unidade", str(texto):
                return Unidade(UUID(texto))
    except ValueError as erro:
        raise ValueError(f"escopo de atribuição inválido: {nivel!r}") from erro
    raise ValueError(f"escopo de atribuição inválido: {nivel!r}")


@dataclass(frozen=True, slots=True)
class Concessao:
    """Uma permissão que uma atribuição ativa dá ao usuário.

    `escopo_maximo` é o `max_scope` da permissão no papel (`global`, `area`, `distrito` ou
    `unidade`); `escopo` é o da atribuição; `valido_ate`, a expiração dela, se houver.
    """

    permissao: str
    escopo_maximo: str
    escopo: Escopo
    valido_ate: datetime | None = None


def permissoes_efetivas(concessoes: Iterable[Concessao]) -> PermissoesEfetivas:
    """União das concessões, com cada escopo limitado pelo escopo máximo da permissão no papel."""
    escopos: dict[str, dict[Escopo, None]] = {}
    for concessao in concessoes:
        escopo = _limitado(concessao.escopo, concessao.escopo_maximo)
        if escopo is not None:
            escopos.setdefault(concessao.permissao, {})[escopo] = None
    return MappingProxyType({codigo: tuple(vistos) for codigo, vistos in escopos.items()})


def _limitado(escopo: Escopo, maximo: str) -> Escopo | None:
    """O escopo efetivo, ou `None` se a atribuição não dá a permissão.

    Máximo `global` é a letra `G` da matriz (arquitetura-conceitual.md § 4): vale em todo lugar,
    seja qual for o escopo da atribuição. Nos demais, vale o escopo da atribuição se estiver
    contido no máximo (o mesmo nível, ou uma unidade, que está na sua área e no seu distrito);
    mais amplo ou do outro eixo (área e distrito não se contêm), nega. Padrão registrado em
    "Perguntas em aberto" da 003.
    """
    match maximo, escopo:
        case "global", _:
            return Global()
        case "area", Area() | Unidade():
            return escopo
        case "distrito", Distrito() | Unidade():
            return escopo
        case "unidade", Unidade():
            return escopo
    return None


@dataclass(frozen=True, slots=True)
class Alvo:
    """Atributos de escopo do recurso verificado: a unidade, o distrito e a área técnica dela."""

    unidade_id: UUID
    distrito_id: int
    area_id: int


def pode(perms: PermissoesEfetivas, perm: str, alvo: Alvo | None = None) -> bool:
    """Diz se o usuário tem `perm` e, havendo alvo, se algum dos seus escopos o cobre.

    Sem alvo (R4.2), basta ter a permissão em algum escopo. Com alvo (R4.3), autoriza se houver
    um escopo `Global`, ou `Area` igual à área da unidade, ou `Distrito` igual ao distrito, ou
    `Unidade` igual à própria unidade. Permissão ausente nega (deny by default).
    """
    escopos = perms.get(perm, ())
    if alvo is None:
        return bool(escopos)
    return any(_cobre(escopo, alvo) for escopo in escopos)


def _cobre(escopo: Escopo, alvo: Alvo) -> bool:
    match escopo:
        case Global():
            return True
        case Area(id=area_id):
            return area_id == alvo.area_id
        case Distrito(id=distrito_id):
            return distrito_id == alvo.distrito_id
        case Unidade(id=unidade_id):
            return unidade_id == alvo.unidade_id


@dataclass(frozen=True, slots=True)
class EscopoLeitura:
    """Escopos de uma permissão separados por nível, para filtrar uma listagem (R4.4).

    Vale o item que estiver em algum deles: tudo, se `global_`; senão, os da área técnica, do
    distrito ou da unidade listados. Sem nenhum, a listagem sai vazia. Vai para o SQL como
    parâmetros (`src/core/escopo.py`), nunca como texto.
    """

    global_: bool = False
    areas: tuple[int, ...] = ()
    distritos: tuple[int, ...] = ()
    unidades: tuple[UUID, ...] = ()


def escopo_de_leitura(perms: PermissoesEfetivas, perm: str) -> EscopoLeitura:
    """O `EscopoLeitura` de `perm`; vazio se o usuário não a tem (deny by default)."""
    escopos = perms.get(perm, ())
    return EscopoLeitura(
        global_=any(isinstance(escopo, Global) for escopo in escopos),
        areas=tuple(sorted(e.id for e in escopos if isinstance(e, Area))),
        distritos=tuple(sorted(e.id for e in escopos if isinstance(e, Distrito))),
        unidades=tuple(sorted(e.id for e in escopos if isinstance(e, Unidade))),
    )
