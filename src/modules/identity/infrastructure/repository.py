"""Repositórios SQLAlchemy para perfil e usuário."""

from sqlalchemy import RowMapping, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.identity.domain.perfil import Perfil
from src.modules.identity.domain.usuario import Usuario
from src.modules.identity.infrastructure.tables import perfil as perfil_table
from src.modules.identity.infrastructure.tables import usuario as usuario_table


class SqlPerfilRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, entity: Perfil) -> Perfil:
        stmt = (
            insert(perfil_table)
            .values(nomeperfil=entity.nome_perfil, permissoes=entity.permissoes)
            .returning(perfil_table.c.idperfil)
        )
        result = await self._session.execute(stmt)
        inserted_id = result.scalar_one()
        return Perfil(
            id_perfil=inserted_id,
            nome_perfil=entity.nome_perfil,
            permissoes=entity.permissoes,
        )

    async def get_by_id(self, id_perfil: int) -> Perfil | None:
        stmt = select(perfil_table).where(perfil_table.c.idperfil == id_perfil)
        result = await self._session.execute(stmt)
        row = result.mappings().one_or_none()
        if row is None:
            return None
        return Perfil(
            id_perfil=row["idperfil"],
            nome_perfil=row["nomeperfil"],
            permissoes=row["permissoes"],
        )

    async def list_all(self) -> list[Perfil]:
        stmt = select(perfil_table).order_by(perfil_table.c.idperfil)
        result = await self._session.execute(stmt)
        return [
            Perfil(
                id_perfil=row["idperfil"],
                nome_perfil=row["nomeperfil"],
                permissoes=row["permissoes"],
            )
            for row in result.mappings().all()
        ]


class SqlUsuarioRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, entity: Usuario) -> Usuario:
        stmt = (
            insert(usuario_table)
            .values(
                nome=entity.nome,
                email=entity.email,
                senhahash=entity.senha_hash,
                doisfatorhabilitado=entity.dois_fator_habilitado,
                doisfatorsegredo=entity.dois_fator_segredo,
                idperfil=entity.id_perfil,
                idunidade=entity.id_unidade,
            )
            .returning(usuario_table.c.idusuario)
        )
        result = await self._session.execute(stmt)
        inserted_id = result.scalar_one()
        return Usuario(
            id_usuario=inserted_id,
            nome=entity.nome,
            email=entity.email,
            senha_hash=entity.senha_hash,
            dois_fator_habilitado=entity.dois_fator_habilitado,
            dois_fator_segredo=entity.dois_fator_segredo,
            id_perfil=entity.id_perfil,
            id_unidade=entity.id_unidade,
        )

    async def get_by_id(self, id_usuario: int) -> Usuario | None:
        stmt = select(usuario_table).where(usuario_table.c.idusuario == id_usuario)
        result = await self._session.execute(stmt)
        row = result.mappings().one_or_none()
        if row is None:
            return None
        return self._to_domain(row)

    async def get_by_email(self, email: str) -> Usuario | None:
        stmt = select(usuario_table).where(usuario_table.c.email == email)
        result = await self._session.execute(stmt)
        row = result.mappings().one_or_none()
        if row is None:
            return None
        return self._to_domain(row)

    async def list_all(self) -> list[Usuario]:
        stmt = select(usuario_table).order_by(usuario_table.c.idusuario)
        result = await self._session.execute(stmt)
        return [self._to_domain(row) for row in result.mappings().all()]

    def _to_domain(self, row: RowMapping) -> Usuario:
        return Usuario(
            id_usuario=int(row["idusuario"]),
            nome=str(row["nome"]),
            email=str(row["email"]),
            senha_hash=str(row["senhahash"]),
            dois_fator_habilitado=bool(row["doisfatorhabilitado"]),
            dois_fator_segredo=str(row["doisfatorsegredo"]) if row["doisfatorsegredo"] else None,
            id_perfil=int(row["idperfil"]),
            id_unidade=int(row["idunidade"]) if row["idunidade"] is not None else None,
        )
