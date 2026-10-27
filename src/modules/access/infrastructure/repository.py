"""Leitura de identidade e permissões com SQL explícito sobre USUARIO e PERFIL."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.access.domain.usuario import UsuarioAutenticado

_GET_USUARIO = text(
    "SELECT u.idusuario, u.nome, u.idperfil, u.idunidade, p.nomeperfil, p.permissoes "
    "FROM usuario AS u "
    "JOIN perfil AS p ON p.idperfil = u.idperfil "
    "WHERE u.idusuario = :id_usuario"
)


class SqlAccessRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_usuario(self, id_usuario: int) -> UsuarioAutenticado | None:
        result = await self._session.execute(_GET_USUARIO, {"id_usuario": id_usuario})
        row = result.mappings().one_or_none()
        if row is None:
            return None
        return UsuarioAutenticado(
            id_usuario=int(row["idusuario"]),
            nome=str(row["nome"]),
            id_perfil=int(row["idperfil"]),
            nome_perfil=str(row["nomeperfil"]),
            permissoes=frozenset(str(row["permissoes"]).split(";")),
            id_unidade=int(row["idunidade"]) if row["idunidade"] is not None else None,
        )
