"""Mapeamento de grupo do diretório para papel (spec 003, R3; design § Rotas,
`/admin/mapeamentos-grupo`).

Função pura: dado o que os grupos do usuário mandam e o que ele já tem de origem `group`, o que
criar e o que remover. As atribuições diretas não entram na conta (R3.3).
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from uuid import UUID

from src.modules.access.domain.atribuicoes import Atribuicao


@dataclass(frozen=True, slots=True, kw_only=True)
class MapeamentoDeGrupo:
    """Os membros ativos de `grupo_id` recebem `papel` no escopo (R3.1); `scope_id` é nulo se
    o escopo é global, como na atribuição."""

    id: UUID
    grupo_id: UUID
    papel: str
    scope_type: str
    scope_id: str | None
    criado_por: UUID


@dataclass(frozen=True, slots=True)
class Recalculo:
    """O que muda nas atribuições derivadas de um usuário."""

    criar: Sequence[MapeamentoDeGrupo]
    remover: Sequence[Atribuicao]

    @property
    def vazio(self) -> bool:
        return not self.criar and not self.remover


def recalcular(
    mapeamentos_dos_grupos: Iterable[MapeamentoDeGrupo], derivadas: Iterable[Atribuicao]
) -> Recalculo:
    """Uma atribuição derivada por mapeamento dos grupos do usuário (R3.2).

    `mapeamentos_dos_grupos` são os mapeamentos dos grupos em que o usuário está;
    `derivadas`, as atribuições dele. Cria a de cada mapeamento que ele ainda não tem e remove as
    de mapeamentos que já não valem para ele (e uma repetida do mesmo mapeamento). Atribuição
    direta é ignorada, mesmo que dê o mesmo papel no mesmo escopo (R3.3).
    """
    esperados = {m.id: m for m in mapeamentos_dos_grupos}
    vistos: set[UUID] = set()
    remover: list[Atribuicao] = []
    for atribuicao in derivadas:
        if atribuicao.origin != "group":
            continue
        mapeamento = atribuicao.group_mapping_id
        if mapeamento in esperados and mapeamento not in vistos:
            vistos.add(mapeamento)
        else:
            remover.append(atribuicao)
    criar = [m for id_, m in esperados.items() if id_ not in vistos]
    return Recalculo(criar=criar, remover=remover)
