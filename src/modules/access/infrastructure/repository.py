"""Repositório do RBAC sobre a sessão SQLAlchemy de quem o usa (SQLAlchemy Core)."""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import Integer, SmallInteger, Uuid, column, or_, select, table, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.access.domain.authorization import Alvo, Concessao, escopo_de
from src.modules.access.infrastructure.tables import permissions, role_assignments, role_permissions

# Só a coluna de versão de `users` (spec 002); a tabela completa é da infraestrutura de identity.
_users = table("users", column("id", Uuid), column("authz_version", Integer))

# Só o que liga a unidade aos escopos (spec 006, 0006): o distrito dela e a área técnica do seu
# tipo. As tabelas completas são da infraestrutura do registry.
_health_units = table(
    "health_units",
    column("id", Uuid),
    column("district_id", SmallInteger),
    column("unit_type_id", SmallInteger),
)
_unit_types = table(
    "unit_types", column("id", SmallInteger), column("technical_area_id", SmallInteger)
)


class SqlRepositorioDePermissoes:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def versao(self, usuario_id: UUID) -> int | None:
        return await self._session.scalar(
            select(_users.c.authz_version).where(_users.c.id == usuario_id)
        )

    async def concessoes(self, usuario_id: UUID, agora: datetime) -> Sequence[Concessao]:
        vigente = or_(
            role_assignments.c.valid_until.is_(None), role_assignments.c.valid_until > agora
        )
        resultado = await self._session.execute(
            select(
                permissions.c.code,
                role_permissions.c.max_scope,
                role_assignments.c.scope_type,
                role_assignments.c.scope_id,
                role_assignments.c.valid_until,
            )
            .select_from(
                role_assignments.join(
                    role_permissions, role_permissions.c.role_id == role_assignments.c.role_id
                ).join(permissions, permissions.c.id == role_permissions.c.permission_id)
            )
            .where(role_assignments.c.user_id == usuario_id, vigente)
        )
        return [
            Concessao(
                permissao=codigo,
                escopo_maximo=escopo_maximo,
                escopo=escopo_de(nivel, id_do_escopo),
                valido_ate=valido_ate,
            )
            for codigo, escopo_maximo, nivel, id_do_escopo, valido_ate in resultado.all()
        ]

    async def invalidar(self, usuario_id: UUID) -> None:
        await self._session.execute(
            update(_users)
            .where(_users.c.id == usuario_id)
            .values(authz_version=_users.c.authz_version + 1)
        )


class SqlResolvedorDeUnidade:
    """`ResolvedorDeAlvo` de `ResourceRef("unidade")` (design da 003 § Verificação)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def alvo(self, id_do_recurso: str) -> Alvo | None:
        try:
            unidade_id = UUID(id_do_recurso)
        except ValueError:
            return None
        resultado = await self._session.execute(
            select(_health_units.c.id, _health_units.c.district_id, _unit_types.c.technical_area_id)
            .select_from(
                _health_units.join(_unit_types, _unit_types.c.id == _health_units.c.unit_type_id)
            )
            .where(_health_units.c.id == unidade_id)
        )
        linha = resultado.one_or_none()
        if linha is None:
            return None
        unidade, distrito, area = linha
        return Alvo(unidade_id=unidade, distrito_id=distrito, area_id=area)
