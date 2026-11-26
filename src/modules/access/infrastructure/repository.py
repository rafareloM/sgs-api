"""Repositório do RBAC sobre a sessão SQLAlchemy de quem o usa (SQLAlchemy Core)."""

from collections.abc import Collection, Sequence
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    Integer,
    SmallInteger,
    String,
    Uuid,
    column,
    delete,
    exists,
    insert,
    or_,
    select,
    table,
    update,
)
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.access.domain.atribuicoes import Atribuicao, DadosDoUsuario, Papel, nivel_exigido
from src.modules.access.domain.authorization import Alvo, Concessao, escopo_de
from src.modules.access.domain.mapeamentos import MapeamentoDeGrupo
from src.modules.access.infrastructure.tables import (
    group_role_mappings,
    permissions,
    role_assignments,
    role_permissions,
    roles,
)

# Só a coluna de versão de `users` (spec 002); a tabela completa é da infraestrutura de identity.
_users = table("users", column("id", Uuid), column("authz_version", Integer))
# Tabelas do módulo identity (spec 004), só as colunas que a leitura dos membros usa.
_users_ativos = table("users", column("id", Uuid), column("is_active", Boolean))
_user_groups = table("user_groups", column("user_id", Uuid), column("group_id", Uuid))
_groups = table("groups", column("id", Uuid))

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
                roles.c.code,
            )
            .select_from(
                role_assignments.join(
                    role_permissions, role_permissions.c.role_id == role_assignments.c.role_id
                )
                .join(permissions, permissions.c.id == role_permissions.c.permission_id)
                .join(roles, roles.c.id == role_assignments.c.role_id)
            )
            .where(role_assignments.c.user_id == usuario_id, vigente)
        )
        return [
            Concessao(
                permissao=codigo,
                escopo_maximo=escopo_maximo,
                escopo=escopo_de(nivel, id_do_escopo),
                valido_ate=valido_ate,
                papel=papel,
            )
            for codigo, escopo_maximo, nivel, id_do_escopo, valido_ate, papel in resultado.all()
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


_usuarios = table(
    "users",
    column("id", Uuid),
    column("username", String),
    column("display_name", String),
    column("email", String),
    column("source", String),
    column("is_active", Boolean),
)
_distritos = table("districts", column("id", SmallInteger))
_areas = table("technical_areas", column("id", SmallInteger))


class SqlRepositorioDeAtribuicoes:
    """Papéis, atribuições e dados básicos do usuário (spec 003, R2 e R5)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def papeis(self) -> Sequence[Papel]:
        return [p for p in [await self._papel_por(c) for c in await self._codigos()] if p]

    async def papel(self, codigo: str) -> Papel | None:
        return await self._papel_por(codigo)

    async def _codigos(self) -> list[str]:
        resultado = await self._session.execute(select(roles.c.code).order_by(roles.c.code))
        return list(resultado.scalars())

    async def _papel_por(self, codigo: str) -> Papel | None:
        linha = (
            await self._session.execute(
                select(roles.c.code, roles.c.name, roles.c.description).where(
                    roles.c.code == codigo
                )
            )
        ).one_or_none()
        if linha is None:
            return None
        escopos = await self._session.execute(
            select(role_permissions.c.max_scope)
            .select_from(role_permissions.join(roles, roles.c.id == role_permissions.c.role_id))
            .where(roles.c.code == codigo)
        )
        return Papel(
            codigo=linha.code,
            nome=linha.name,
            descricao=linha.description,
            escopo_exigido=nivel_exigido(escopos.scalars()),
        )

    async def usuario(self, usuario_id: UUID) -> DadosDoUsuario | None:
        linha = (
            (await self._session.execute(select(_usuarios).where(_usuarios.c.id == usuario_id)))
            .mappings()
            .one_or_none()
        )
        return None if linha is None else DadosDoUsuario(**linha)

    async def atribuicoes(self, usuario_id: UUID | None, agora: datetime) -> Sequence[Atribuicao]:
        consulta_ = (
            select(
                role_assignments.c.id,
                role_assignments.c.user_id,
                roles.c.code.label("papel"),
                role_assignments.c.scope_type,
                role_assignments.c.scope_id,
                role_assignments.c.origin,
                role_assignments.c.valid_until,
                role_assignments.c.granted_by,
                role_assignments.c.group_mapping_id,
            )
            .select_from(role_assignments.join(roles, roles.c.id == role_assignments.c.role_id))
            .where(
                or_(
                    role_assignments.c.valid_until.is_(None),
                    role_assignments.c.valid_until > agora,
                )
            )
            .order_by(roles.c.code, role_assignments.c.id)
        )
        if usuario_id is not None:
            consulta_ = consulta_.where(role_assignments.c.user_id == usuario_id)
        resultado = await self._session.execute(consulta_)
        return [Atribuicao(**linha) for linha in resultado.mappings()]

    async def atribuicao(self, id_: UUID) -> Atribuicao | None:
        for atribuicao in await self.atribuicoes(None, datetime.min.replace(tzinfo=UTC)):
            if atribuicao.id == id_:
                return atribuicao
        return None

    async def escopo_existe(self, nivel: str, id_do_escopo: str) -> bool:
        try:
            if nivel == "area":
                alvo = select(_areas.c.id).where(_areas.c.id == int(id_do_escopo))
            elif nivel == "distrito":
                alvo = select(_distritos.c.id).where(_distritos.c.id == int(id_do_escopo))
            elif nivel == "unidade":
                alvo = select(_health_units.c.id).where(_health_units.c.id == UUID(id_do_escopo))
            else:
                return False
        except ValueError:
            return False
        return (await self._session.scalar(alvo)) is not None

    async def inserir(self, atribuicao: Atribuicao) -> None:
        papel_id = select(roles.c.id).where(roles.c.code == atribuicao.papel).scalar_subquery()
        await self._session.execute(
            insert(role_assignments).values(
                id=atribuicao.id,
                user_id=atribuicao.user_id,
                role_id=papel_id,
                scope_type=atribuicao.scope_type,
                scope_id=atribuicao.scope_id,
                origin=atribuicao.origin,
                valid_until=atribuicao.valid_until,
                granted_by=atribuicao.granted_by,
                group_mapping_id=atribuicao.group_mapping_id,
            )
        )

    async def remover(self, id_: UUID) -> None:
        await self._session.execute(delete(role_assignments).where(role_assignments.c.id == id_))


_SELECAO_DE_DERIVADA = select(
    role_assignments.c.id,
    role_assignments.c.user_id,
    roles.c.code.label("papel"),
    role_assignments.c.scope_type,
    role_assignments.c.scope_id,
    role_assignments.c.origin,
    role_assignments.c.valid_until,
    role_assignments.c.granted_by,
    role_assignments.c.group_mapping_id,
).select_from(role_assignments.join(roles, roles.c.id == role_assignments.c.role_id))

_SELECAO_DE_MAPEAMENTO = select(
    group_role_mappings.c.id,
    group_role_mappings.c.group_id.label("grupo_id"),
    roles.c.code.label("papel"),
    group_role_mappings.c.scope_type,
    group_role_mappings.c.scope_id,
    group_role_mappings.c.created_by.label("criado_por"),
).select_from(group_role_mappings.join(roles, roles.c.id == group_role_mappings.c.role_id))


class SqlRepositorioDeMapeamentos:
    """`RepositorioDeMapeamentos` (003/R3) sobre `group_role_mappings` e `role_assignments`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def grupo_existe(self, grupo_id: UUID) -> bool:
        return bool(await self._session.scalar(select(exists().where(_groups.c.id == grupo_id))))

    async def ha_mapeamento(
        self, grupo_id: UUID, papel: str, escopo_tipo: str, escopo_id: str | None
    ) -> bool:
        papel_id = select(roles.c.id).where(roles.c.code == papel).scalar_subquery()
        return bool(
            await self._session.scalar(
                select(
                    exists().where(
                        group_role_mappings.c.group_id == grupo_id,
                        group_role_mappings.c.role_id == papel_id,
                        group_role_mappings.c.scope_type == escopo_tipo,
                        group_role_mappings.c.scope_id.is_not_distinct_from(escopo_id),
                    )
                )
            )
        )

    async def inserir(self, mapeamento: MapeamentoDeGrupo) -> None:
        papel_id = select(roles.c.id).where(roles.c.code == mapeamento.papel).scalar_subquery()
        await self._session.execute(
            insert(group_role_mappings).values(
                id=mapeamento.id,
                group_id=mapeamento.grupo_id,
                role_id=papel_id,
                scope_type=mapeamento.scope_type,
                scope_id=mapeamento.scope_id,
                created_by=mapeamento.criado_por,
            )
        )

    async def obter(self, mapeamento_id: UUID) -> MapeamentoDeGrupo | None:
        resultado = await self._session.execute(
            _SELECAO_DE_MAPEAMENTO.where(group_role_mappings.c.id == mapeamento_id)
        )
        linha = resultado.mappings().one_or_none()
        return None if linha is None else MapeamentoDeGrupo(**linha)

    async def remover(self, mapeamento_id: UUID) -> None:
        await self._session.execute(
            delete(group_role_mappings).where(group_role_mappings.c.id == mapeamento_id)
        )

    async def listar(self) -> Sequence[MapeamentoDeGrupo]:
        # O id é uuid7: a ordem do id é a de criação.
        resultado = await self._session.execute(
            _SELECAO_DE_MAPEAMENTO.order_by(group_role_mappings.c.id)
        )
        return [MapeamentoDeGrupo(**linha) for linha in resultado.mappings()]

    async def dos_grupos(self, grupos: Collection[UUID]) -> Sequence[MapeamentoDeGrupo]:
        if not grupos:
            return []
        resultado = await self._session.execute(
            _SELECAO_DE_MAPEAMENTO.where(group_role_mappings.c.group_id.in_(list(grupos)))
        )
        return [MapeamentoDeGrupo(**linha) for linha in resultado.mappings()]

    async def derivadas_do_usuario(self, usuario_id: UUID) -> Sequence[Atribuicao]:
        resultado = await self._session.execute(
            _SELECAO_DE_DERIVADA.where(
                role_assignments.c.user_id == usuario_id, role_assignments.c.origin == "group"
            ).order_by(role_assignments.c.id)
        )
        return [Atribuicao(**linha) for linha in resultado.mappings()]

    async def derivadas_do_mapeamento(self, mapeamento_id: UUID) -> Sequence[Atribuicao]:
        resultado = await self._session.execute(
            _SELECAO_DE_DERIVADA.where(
                role_assignments.c.group_mapping_id == mapeamento_id
            ).order_by(role_assignments.c.id)
        )
        return [Atribuicao(**linha) for linha in resultado.mappings()]


class SqlMembrosDeGrupo:
    """`MembrosDeGrupo` sobre `user_groups` da spec 004 (004/T4): os membros do grupo com conta
    ativa, de qualquer origem do grupo (003/R3.1)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def membros_ativos(self, grupo_id: UUID) -> frozenset[UUID]:
        consulta = (
            select(_user_groups.c.user_id)
            .select_from(
                _user_groups.join(_users_ativos, _users_ativos.c.id == _user_groups.c.user_id)
            )
            .where(_user_groups.c.group_id == grupo_id, _users_ativos.c.is_active)
        )
        return frozenset((await self._session.scalars(consulta)).all())
