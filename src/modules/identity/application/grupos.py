"""Espelho dos grupos de um usuário no login por diretório (spec 004, design § Login LDAP, passo
6, e § Login OIDC, passo 4; R2.3, R3.3).

Extraído do login LDAP antes da 004/T7, que o repetiria uma terceira vez (revisão da frente A,
N3): grava os grupos da origem, troca as associações do usuário naquela origem e recalcula as
atribuições derivadas da 003 com todos os grupos atuais dele, de todas as origens (003/R3.2).
"""

from collections.abc import Callable, Iterable
from datetime import datetime
from typing import Final
from uuid import UUID

from src.modules.access.application.mapeamentos import recalcular_derivadas_do_usuario
from src.modules.access.domain.ports import (
    RepositorioDeAtribuicoes,
    RepositorioDeMapeamentos,
    RepositorioDePermissoes,
)
from src.modules.audit.application.registrar import Ator, AuditStore
from src.modules.identity.application.login import ORIGEM_API, Origem
from src.modules.identity.domain.espelho_diretorio import OrigemDeGrupo
from src.modules.identity.domain.ports import DirectoryRepository

_OUTRA: Final[dict[OrigemDeGrupo, OrigemDeGrupo]] = {"ldap": "oidc", "oidc": "ldap"}


async def espelhar_grupos(
    usuario_id: UUID,
    origem_dos_grupos: OrigemDeGrupo,
    grupos: Iterable[tuple[str, str]],
    *,
    repositorio: DirectoryRepository,
    mapeamentos: RepositorioDeMapeamentos,
    atribuicoes: RepositorioDeAtribuicoes,
    permissoes: RepositorioDePermissoes,
    auditoria: AuditStore,
    origem: Origem,
    gerar_id: Callable[[], UUID],
    agora: datetime,
) -> None:
    """`grupos` são pares (`external_id`, nome) da origem."""
    ids: set[UUID] = set()
    for external_id, nome in grupos:
        gravado = await repositorio.upsert_group(origem_dos_grupos, external_id, nome, agora)
        ids.add(gravado.id)
    await repositorio.replace_user_groups(usuario_id, origem_dos_grupos, ids)
    outros = await repositorio.groups_of_user(usuario_id, _OUTRA[origem_dos_grupos])
    await recalcular_derivadas_do_usuario(
        usuario_id,
        frozenset(ids) | outros,
        # O recálculo é ato do sistema, disparado pelo login (013/R1.1).
        ator=Ator(
            tipo="sistema",
            origem=ORIGEM_API,
            ip=origem.ip,
            user_agent=origem.user_agent,
            request_id=origem.request_id,
        ),
        mapeamentos=mapeamentos,
        atribuicoes=atribuicoes,
        permissoes=permissoes,
        auditoria=auditoria,
        gerar_id=gerar_id,
    )
