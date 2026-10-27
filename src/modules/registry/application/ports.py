"""Portas de escrita e leitura do cadastro."""

from collections.abc import Mapping
from typing import Any, Protocol


class RegistryStore(Protocol):
    async def get_unidade(self, unidade_id: int) -> dict[str, Any] | None: ...

    async def list_unidades(
        self, *, id_unidade: int | None, pagina: int, tamanho: int
    ) -> dict[str, Any]: ...

    async def create_unidade(self, dados: Mapping[str, Any], autor_id: int) -> dict[str, Any]: ...

    async def update_status(
        self,
        unidade_id: int,
        status: str,
        versao: int,
        autor_id: int,
        motivo: str | None,
    ) -> dict[str, Any] | None: ...

    async def get_equipamento(self, equipamento_id: int) -> dict[str, Any] | None: ...

    async def list_equipamentos(self, unidade_id: int | None) -> list[dict[str, Any]]: ...

    async def create_equipamento(
        self, unidade_id: int | None, dados: Mapping[str, Any]
    ) -> dict[str, Any]: ...

    async def update_equipamento(
        self, equipamento_id: int, dados: Mapping[str, Any]
    ) -> dict[str, Any] | None: ...

    async def delete_equipamento(self, equipamento_id: int) -> bool: ...
