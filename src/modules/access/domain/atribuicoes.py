"""Atribuição de papéis (spec 003, R2): escopo exigido por papel e segregação de funções."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

NIVEIS = ("global", "area", "distrito", "unidade")


def nivel_exigido(escopos_maximos: Iterable[str]) -> str:
    """O escopo que a atribuição do papel deve ter (R2.1): o mais restrito entre os escopos
    máximos das permissões do papel (matriz da 003). `GESTOR_UNIDADE` (tudo `unidade`) exige
    `unidade`; `TECNICO_DISTRITAL` (D e G) exige `distrito`; um papel só de G, `global`.
    Atribuir num escopo mais amplo (R2.2) daria mais do que o papel prevê; num mais estreito, a
    permissão de nível maior seria perdida (`_limitado` da 003)."""
    presentes = set(escopos_maximos)
    for nivel in reversed(NIVEIS):
        if nivel in presentes:
            return nivel
    return "global"


@dataclass(frozen=True, slots=True, kw_only=True)
class Atribuicao:
    """Um papel atribuído a um usuário num escopo.

    `origin` é `direct` (pela rota de administração) ou `group` (derivada de um mapeamento de
    grupo, R3); `granted_by`, quem atribuiu, se direta; `valid_until`, a expiração (R2.3);
    `group_mapping_id`, o mapeamento que gerou a derivada (nulo se direta).
    """

    id: UUID
    user_id: UUID
    papel: str
    scope_type: str
    scope_id: str | None
    origin: str
    valid_until: datetime | None
    granted_by: UUID | None
    group_mapping_id: UUID | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class Papel:
    codigo: str
    nome: str
    descricao: str
    escopo_exigido: str


@dataclass(frozen=True, slots=True, kw_only=True)
class DadosDoUsuario:
    id: UUID
    username: str
    display_name: str
    email: str | None
    source: str
    is_active: bool
