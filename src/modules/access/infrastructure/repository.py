"""Repositório do RBAC sobre a sessão SQLAlchemy de quem o usa (SQLAlchemy Core)."""

from collections.abc import Collection, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Integer,
    SmallInteger,
    Uuid,
    column,
    delete,
    exists,
    func,
    insert,
    or_,
    select,
    table,
    update,
)
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.access.domain.atribuicoes import Atribuicao, colunas_do_escopo
from src.modules.access.domain.authorization import (
    Alvo,
    Area,
    Concessao,
    Distrito,
    Escopo,
    Global,
    PapelAtribuido,
    Unidade,
    escopo_de,
)
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
_districts = table("districts", column("id", SmallInteger))
_technical_areas = table("technical_areas", column("id", SmallInteger))

# Faixa de `smallint`, o tipo do id do distrito e da área técnica.
_SMALLINT = range(1, 32768)


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

    async def papeis(self, usuario_id: UUID, agora: datetime) -> Sequence[PapelAtribuido]:
        vigente = or_(
            role_assignments.c.valid_until.is_(None), role_assignments.c.valid_until > agora
        )
        resultado = await self._session.execute(
            select(
                roles.c.code,
                roles.c.name,
                role_assignments.c.scope_type,
                role_assignments.c.scope_id,
                role_assignments.c.origin,
                role_assignments.c.valid_until,
            )
            .select_from(role_assignments.join(roles, roles.c.id == role_assignments.c.role_id))
            .where(role_assignments.c.user_id == usuario_id, vigente)
            .order_by(roles.c.code, role_assignments.c.scope_type, role_assignments.c.scope_id)
        )
        return [
            PapelAtribuido(
                codigo=codigo,
                nome=nome,
                escopo=escopo_de(nivel, id_do_escopo),
                origem=origem,
                valido_ate=valido_ate,
            )
            for codigo, nome, nivel, id_do_escopo, origem, valido_ate in resultado.all()
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


class SqlRepositorioDeAtribuicoes:
    """`RepositorioDeAtribuicoes` (003/R2) sobre `role_assignments`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def escopos_maximos(self, papel: str) -> frozenset[str] | None:
        papel_id = await self._session.scalar(select(roles.c.id).where(roles.c.code == papel))
        if papel_id is None:
            return None
        resultado = await self._session.scalars(
            select(role_permissions.c.max_scope).where(role_permissions.c.role_id == papel_id)
        )
        return frozenset(resultado.all())

    async def escopo_existe(self, escopo: Escopo) -> bool:
        match escopo:
            case Global():
                return True
            case Area(id=id_):
                return id_ in _SMALLINT and await self._existe(_technical_areas.c.id == id_)
            case Distrito(id=id_):
                return id_ in _SMALLINT and await self._existe(_districts.c.id == id_)
            case Unidade(id=id_):
                return await self._existe(_health_units.c.id == id_)

    async def _existe(self, condicao: Any) -> bool:
        return bool(await self._session.scalar(select(exists().where(condicao))))

    async def ha_direta_vigente(
        self, usuario_id: UUID, papel: str, escopo: Escopo, agora: datetime
    ) -> bool:
        nivel, id_do_escopo = colunas_do_escopo(escopo)
        return await self._existe(
            (role_assignments.c.user_id == usuario_id)
            & (role_assignments.c.role_id == _id_do_papel(papel))
            & (role_assignments.c.scope_type == nivel)
            & role_assignments.c.scope_id.is_not_distinct_from(id_do_escopo)
            & (role_assignments.c.origin == "direct")
            & _vigente(agora)
        )

    async def inserir(self, atribuicao: Atribuicao) -> None:
        nivel, id_do_escopo = colunas_do_escopo(atribuicao.escopo)
        await self._session.execute(
            insert(role_assignments).values(
                id=atribuicao.id,
                user_id=atribuicao.usuario_id,
                role_id=_id_do_papel(atribuicao.papel),
                scope_type=nivel,
                scope_id=id_do_escopo,
                origin=atribuicao.origem,
                group_mapping_id=atribuicao.mapeamento_id,
                granted_by=atribuicao.concedida_por,
                valid_until=atribuicao.valido_ate,
            )
        )

    async def obter(self, atribuicao_id: UUID) -> Atribuicao | None:
        resultado = await self._session.execute(
            _SELECAO.where(role_assignments.c.id == atribuicao_id)
        )
        linha = resultado.one_or_none()
        return None if linha is None else _atribuicao(*linha)

    async def remover(self, atribuicao_id: UUID) -> None:
        await self._session.execute(
            delete(role_assignments).where(role_assignments.c.id == atribuicao_id)
        )

    async def listar(
        self, usuario_id: UUID | None, agora: datetime, *, deslocamento: int, limite: int
    ) -> tuple[Sequence[Atribuicao], int]:
        filtro = _vigente(agora)
        if usuario_id is not None:
            filtro = filtro & (role_assignments.c.user_id == usuario_id)
        total = await self._session.scalar(
            select(func.count()).select_from(role_assignments).where(filtro)
        )
        resultado = await self._session.execute(
            _SELECAO.where(filtro)
            .order_by(role_assignments.c.id)
            .offset(deslocamento)
            .limit(limite)
        )
        return [_atribuicao(*linha) for linha in resultado.all()], int(total or 0)


def _vigente(agora: datetime) -> Any:
    return or_(role_assignments.c.valid_until.is_(None), role_assignments.c.valid_until > agora)


def _id_do_papel(papel: str) -> Any:
    return select(roles.c.id).where(roles.c.code == papel).scalar_subquery()


_SELECAO = select(
    role_assignments.c.id,
    role_assignments.c.user_id,
    roles.c.code,
    role_assignments.c.scope_type,
    role_assignments.c.scope_id,
    role_assignments.c.origin,
    role_assignments.c.granted_by,
    role_assignments.c.valid_until,
    role_assignments.c.group_mapping_id,
).select_from(role_assignments.join(roles, roles.c.id == role_assignments.c.role_id))


def _atribuicao(
    id_: UUID,
    usuario: UUID,
    papel: str,
    nivel: str,
    id_do_escopo: str | None,
    origem: str,
    concedida_por: UUID | None,
    valido_ate: datetime | None,
    mapeamento_id: UUID | None,
) -> Atribuicao:
    return Atribuicao(
        id=id_,
        usuario_id=usuario,
        papel=papel,
        escopo=escopo_de(nivel, id_do_escopo),
        origem=origem,
        concedida_por=concedida_por,
        valido_ate=valido_ate,
        mapeamento_id=mapeamento_id,
    )


class SqlRepositorioDeMapeamentos:
    """`RepositorioDeMapeamentos` (003/R3) sobre `group_role_mappings` e `role_assignments`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def ha_mapeamento(self, grupo_id: UUID, papel: str, escopo: Escopo) -> bool:
        nivel, id_do_escopo = colunas_do_escopo(escopo)
        return bool(
            await self._session.scalar(
                select(
                    exists().where(
                        (group_role_mappings.c.group_id == grupo_id)
                        & (group_role_mappings.c.role_id == _id_do_papel(papel))
                        & (group_role_mappings.c.scope_type == nivel)
                        & group_role_mappings.c.scope_id.is_not_distinct_from(id_do_escopo)
                    )
                )
            )
        )

    async def inserir(self, mapeamento: MapeamentoDeGrupo) -> None:
        nivel, id_do_escopo = colunas_do_escopo(mapeamento.escopo)
        await self._session.execute(
            insert(group_role_mappings).values(
                id=mapeamento.id,
                group_id=mapeamento.grupo_id,
                role_id=_id_do_papel(mapeamento.papel),
                scope_type=nivel,
                scope_id=id_do_escopo,
                created_by=mapeamento.criado_por,
            )
        )

    async def obter(self, mapeamento_id: UUID) -> MapeamentoDeGrupo | None:
        resultado = await self._session.execute(
            _SELECAO_DE_MAPEAMENTO.where(group_role_mappings.c.id == mapeamento_id)
        )
        linha = resultado.one_or_none()
        return None if linha is None else _mapeamento(*linha)

    async def remover(self, mapeamento_id: UUID) -> None:
        await self._session.execute(
            delete(group_role_mappings).where(group_role_mappings.c.id == mapeamento_id)
        )

    async def listar(
        self, *, deslocamento: int, limite: int
    ) -> tuple[Sequence[MapeamentoDeGrupo], int]:
        total = await self._session.scalar(select(func.count()).select_from(group_role_mappings))
        resultado = await self._session.execute(
            _SELECAO_DE_MAPEAMENTO.order_by(group_role_mappings.c.id)
            .offset(deslocamento)
            .limit(limite)
        )
        return [_mapeamento(*linha) for linha in resultado.all()], int(total or 0)

    async def dos_grupos(self, grupos: Collection[UUID]) -> Sequence[MapeamentoDeGrupo]:
        if not grupos:
            return []
        resultado = await self._session.execute(
            _SELECAO_DE_MAPEAMENTO.where(group_role_mappings.c.group_id.in_(list(grupos)))
        )
        return [_mapeamento(*linha) for linha in resultado.all()]

    async def derivadas_do_usuario(self, usuario_id: UUID) -> Sequence[Atribuicao]:
        resultado = await self._session.execute(
            _SELECAO.where(
                role_assignments.c.user_id == usuario_id, role_assignments.c.origin == "group"
            ).order_by(role_assignments.c.id)
        )
        return [_atribuicao(*linha) for linha in resultado.all()]

    async def derivadas_do_mapeamento(self, mapeamento_id: UUID) -> Sequence[Atribuicao]:
        resultado = await self._session.execute(
            _SELECAO.where(role_assignments.c.group_mapping_id == mapeamento_id).order_by(
                role_assignments.c.id
            )
        )
        return [_atribuicao(*linha) for linha in resultado.all()]


class SemMembrosDeGrupo:
    """`MembrosDeGrupo` até a spec 004 criar `groups` e `user_groups` (004/T1): nenhum grupo tem
    membros, então um mapeamento novo não atribui nada até a sincronização do diretório chamar o
    recálculo (003/R3.2). A 004/T1 troca esta classe pela leitura de `user_groups`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def membros_ativos(self, grupo_id: UUID) -> frozenset[UUID]:
        return frozenset()


_SELECAO_DE_MAPEAMENTO = select(
    group_role_mappings.c.id,
    group_role_mappings.c.group_id,
    roles.c.code,
    group_role_mappings.c.scope_type,
    group_role_mappings.c.scope_id,
    group_role_mappings.c.created_by,
).select_from(group_role_mappings.join(roles, roles.c.id == group_role_mappings.c.role_id))


def _mapeamento(
    id_: UUID,
    grupo: UUID,
    papel: str,
    nivel: str,
    id_do_escopo: str | None,
    criado_por: UUID,
) -> MapeamentoDeGrupo:
    return MapeamentoDeGrupo(
        id=id_,
        grupo_id=grupo,
        papel=papel,
        escopo=escopo_de(nivel, id_do_escopo),
        criado_por=criado_por,
    )
