"""Diretório LDAP: o que a API lê dele e a porta do adaptador (spec 004, design § Portas e
adaptadores).

O adaptador (`ldap3`) fica em `infrastructure/ldap3_directory.py`.
"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class DirectoryUser:
    external_id: str  # entryUUID/objectGUID; o DN se LDAP_ATTR_ID estiver vazio (R1.5)
    dn: str
    login: str  # minúsculo
    email: str | None  # minúsculo
    display_name: str


@dataclass(frozen=True)
class DirectoryGroup:
    external_id: str
    dn: str
    name: str
    member_dns: frozenset[str]


@dataclass(frozen=True)
class DirectorySnapshot:
    users: tuple[DirectoryUser, ...]
    groups: tuple[DirectoryGroup, ...]


class DirectoryUnavailable(Exception):  # noqa: N818 - nome do design da 004
    """Conexão, TLS recusado (R1.13), timeout ou erro do servidor. Nunca leva a senha."""


class DirectoryPort(Protocol):
    async def snapshot(self) -> DirectorySnapshot:
        """Todos os usuários e grupos, em busca paginada e só com os atributos configurados
        (R1.2 a R1.4)."""
        ...

    async def find_user(self, login: str) -> DirectoryUser | None:
        """O usuário com esse login, pela conta de serviço; o login é escapado (R2.1, R2.2)."""
        ...

    async def verify_password(self, dn: str, password: str) -> bool:
        """Confere a senha por bind com o DN; senha vazia é recusada sem bind (R2.1, R2.4)."""
        ...

    async def groups_of(self, user: DirectoryUser) -> tuple[DirectoryGroup, ...]:
        """Os grupos de que o usuário é membro (R2.3)."""
        ...
