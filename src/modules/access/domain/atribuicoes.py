"""Atribuição de papel a um usuário (spec 003, R2; design § Rotas, `/admin/atribuicoes`).

Funções puras: qual nível de escopo um papel aceita e como o escopo vira as colunas
`scope_type` e `scope_id`.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from src.modules.access.domain.authorization import Area, Distrito, Escopo, Global, Unidade

GLOBAL = "global"


@dataclass(frozen=True, slots=True)
class Atribuicao:
    """Um papel atribuído a um usuário num escopo.

    `origem` é `direct` (pela rota de administração) ou `group` (derivada de um mapeamento de
    grupo, R3); `concedida_por`, quem atribuiu, se direta; `valido_ate`, a expiração (R2.3);
    `mapeamento_id`, o mapeamento que gerou a derivada (nulo se direta).
    """

    id: UUID
    usuario_id: UUID
    papel: str
    escopo: Escopo
    origem: str
    concedida_por: UUID | None = None
    valido_ate: datetime | None = None
    mapeamento_id: UUID | None = None


def niveis_aceitos(escopos_maximos: Iterable[str]) -> frozenset[str]:
    """Os níveis de escopo que uma atribuição do papel pode ter (R2.1, R2.2).

    `escopos_maximos` são os `max_scope` das permissões do papel. Vale o nível não global delas
    (`GESTOR_UNIDADE` → `unidade`, `TECNICO_DISTRITAL` → `distrito`, `COORD_TECNICO` → `area`):
    global seria maior que o permitido, e outro nível daria só parte das permissões. Papel só com
    `G` aceita só `global`, porque nele o escopo não restringe nada (nota da 003/T3 em
    "Perguntas em aberto"). O escopo pedido tem de ser exatamente um desses níveis.
    """
    niveis = frozenset(escopos_maximos) - {GLOBAL}
    return niveis or frozenset({GLOBAL})


def colunas_do_escopo(escopo: Escopo) -> tuple[str, str | None]:
    """`scope_type` e `scope_id` (texto; nulo se global), o inverso de `escopo_de`."""
    match escopo:
        case Global():
            return GLOBAL, None
        case Area(id=id_):
            return "area", str(id_)
        case Distrito(id=id_):
            return "distrito", str(id_)
        case Unidade(id=id_):
            return "unidade", str(id_)
