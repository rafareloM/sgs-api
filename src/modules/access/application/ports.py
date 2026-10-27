"""Portas de leitura necessárias à autorização."""

from typing import Protocol

from src.modules.access.domain.usuario import UsuarioAutenticado


class AccessReader(Protocol):
    async def get_usuario(self, id_usuario: int) -> UsuarioAutenticado | None: ...
