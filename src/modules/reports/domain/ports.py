"""Portas do módulo de relatórios: repositório de pedidos (spec 005, T1).

O repositório trabalha sobre a transação de quem o usa: quem chama abre, confirma ou desfaz.
"""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from src.modules.reports.domain.pedidos import (
    Conclusao,
    Pagina,
    PedidoDeRelatorio,
    StatusDoPedido,
)


class RepositorioDePedidos(Protocol):
    async def criar(self, pedido: PedidoDeRelatorio) -> None:
        """Grava o pedido `pendente` com filtros e escopo (R1.1, R1.3), em JSON: tupla vira lista,
        UUID e data viram texto, e é assim que `obter` e `listar` os devolvem."""
        ...

    async def obter(self, pedido_id: UUID) -> PedidoDeRelatorio | None: ...

    async def marcar_gerando(self, pedido_id: UUID, agora: datetime) -> bool:
        """`gerando` só se `pendente` (design § Geração e envio, passo 1); `False` se não."""
        ...

    async def concluir(self, pedido_id: UUID, conclusao: Conclusao, agora: datetime) -> bool:
        """`concluido` com objeto, tamanho, hash, assinatura e vencimento, só se `gerando`
        (R2.5, R5.1); `False` se não."""
        ...

    async def falhar(self, pedido_id: UUID, erro: str, agora: datetime) -> bool:
        """`falhou` com a mensagem genérica (cortada em `ERRO_MAX`), só se `pendente` ou
        `gerando` (R2.6); `False` se não, e um pedido concluído fica como está."""
        ...

    async def marcar_interrompidos(self, agora: datetime) -> tuple[UUID, ...]:
        """Na subida, `pendente` e `gerando` viram `falhou` com "Interrompido" (design § Geração
        e envio, passo 8). Devolve os ids marcados."""
        ...

    async def listar(
        self, *, solicitado_por: UUID | None, status: StatusDoPedido | None, pagina: Pagina
    ) -> tuple[list[PedidoDeRelatorio], int]:
        """Do mais recente ao mais antigo, com o total. `solicitado_por=None` lista os de todos
        (`GESTOR_DADOS`, R3.5)."""
        ...
