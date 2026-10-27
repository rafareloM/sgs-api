"""Porta de leitura do resumo da rede."""

from typing import Any, Protocol


class DashboardReader(Protocol):
    async def resumo(self, *, distrito: str | None, id_unidade: int | None) -> dict[str, Any]: ...
