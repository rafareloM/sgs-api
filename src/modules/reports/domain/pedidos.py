"""Pedido de relatório e o ciclo de status dele (spec 005; design § Modelo de dados e § Fluxo).

`pendente` → `gerando` → `concluido` ou `falhou`. Os filtros e o escopo ficam como foram
gravados, em JSON (tupla vira lista; UUID e data viram texto): a validação dos filtros e a
comparação de escopo são da T12, e quem lê o pedido reconstrói os tipos.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final
from uuid import UUID

from src.modules.reports.domain.assinatura import Assinatura

ERRO_MAX: Final = 200
ERRO_INTERROMPIDO: Final = "Interrompido"


class TipoDeRelatorio(StrEnum):
    """R1.2."""

    INVENTARIO_UNIDADES = "inventario_unidades"
    TRILHA_AUDITORIA = "trilha_auditoria"


class FormatoDeRelatorio(StrEnum):
    """R1.2."""

    CSV = "csv"
    XLSX = "xlsx"


class StatusDoPedido(StrEnum):
    """R1.1, R2.5, R2.6."""

    PENDENTE = "pendente"
    GERANDO = "gerando"
    CONCLUIDO = "concluido"
    FALHOU = "falhou"


STATUS_ABERTOS: Final = (StatusDoPedido.PENDENTE, StatusDoPedido.GERANDO)


@dataclass(frozen=True, slots=True, kw_only=True)
class PedidoDeRelatorio:
    id: UUID
    tipo: TipoDeRelatorio
    formato: FormatoDeRelatorio
    filtros: Mapping[str, object]  # já validados no pedido (R1.5)
    solicitado_por: UUID
    escopo: Mapping[str, object]  # `scope_snapshot`: o escopo de leitura usado (R1.3)
    status: StatusDoPedido
    criado_em: datetime
    atualizado_em: datetime
    iniciado_em: datetime | None = None
    terminado_em: datetime | None = None  # `concluido` ou `falhou`
    vence_em: datetime | None = None
    bucket: str | None = None
    chave: str | None = None
    versao: str | None = None  # versão do objeto, para remover exatamente o gravado (R2.8)
    tamanho_bytes: int | None = None
    sha256: str | None = None  # hex
    assinatura: Assinatura | None = None  # R5.1
    erro: str | None = None  # mensagem genérica (R2.6)


@dataclass(frozen=True, slots=True, kw_only=True)
class Conclusao:
    """O que a conclusão grava no pedido (design § Geração e envio, passo 6; R2.5, R5.1)."""

    bucket: str
    chave: str
    versao: str | None
    tamanho_bytes: int
    sha256: str  # hex
    assinatura: Assinatura
    vence_em: datetime


@dataclass(frozen=True, slots=True)
class Pagina:
    numero: int
    tamanho: int

    @property
    def offset(self) -> int:
        return (self.numero - 1) * self.tamanho


def novo_pedido(
    *,
    id: UUID,
    tipo: TipoDeRelatorio,
    formato: FormatoDeRelatorio,
    filtros: Mapping[str, object],
    solicitado_por: UUID,
    escopo: Mapping[str, object],
    agora: datetime,
) -> PedidoDeRelatorio:
    """Pedido `pendente` (R1.1), com o escopo de quem pediu (R1.3)."""
    return PedidoDeRelatorio(
        id=id,
        tipo=tipo,
        formato=formato,
        filtros=filtros,
        solicitado_por=solicitado_por,
        escopo=escopo,
        status=StatusDoPedido.PENDENTE,
        criado_em=agora,
        atualizado_em=agora,
    )
