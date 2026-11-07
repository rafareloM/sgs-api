"""Portas do módulo de cadastro.

Os repositórios trabalham sobre a transação de quem os usa (a da requisição, aberta pela
dependência `SessaoDeNegocio` da camada api): quem chama abre, confirma ou desfaz.
"""

from typing import Protocol
from uuid import UUID

from src.modules.registry.domain.unidade import DadosDaUnidade, Unidade


class RepositorioDeUnidades(Protocol):
    async def area_do_tipo(self, unit_type_id: int) -> int | None:
        """Área técnica do tipo de unidade; `None` se o tipo não existe ou está desativado."""
        ...

    async def distrito_ativo(self, district_id: int) -> bool:
        """Se o distrito sanitário existe e está ativo."""
        ...

    async def inserir(self, id_: UUID, dados: DadosDaUnidade) -> Unidade | None:
        """Grava a unidade nova e a devolve como ficou no banco; `None`, sem gravar nada, se ela
        repete o CNES ou o nome normalizado no distrito de outra (006/R1.3, R1.4)."""
        ...

    async def com_cnes(self, cnes: str) -> UUID | None:
        """Id da unidade com esse CNES, se houver."""
        ...

    async def com_nome(self, district_id: int, name: str) -> UUID | None:
        """Id da unidade do distrito com o mesmo nome normalizado (`fn_normalize_name`), se
        houver."""
        ...
