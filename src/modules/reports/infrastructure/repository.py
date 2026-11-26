"""Repositório de pedidos de relatório sobre a sessão SQLAlchemy de quem o usa (SQLAlchemy Core).

Design da 005 § Modelo de dados. As consultas de dados dos relatórios (SQL explícito, ADR-0009)
são outra coisa e ficam em `infrastructure/sql/` (T11).
"""

import json
from collections.abc import Mapping
from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import RowMapping, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.reports.domain.assinatura import Assinatura
from src.modules.reports.domain.pedidos import (
    ERRO_INTERROMPIDO,
    ERRO_MAX,
    STATUS_ABERTOS,
    Conclusao,
    FormatoDeRelatorio,
    Pagina,
    PedidoDeRelatorio,
    StatusDoPedido,
    TipoDeRelatorio,
)
from src.modules.reports.infrastructure.tables import report_jobs

_t = report_jobs.c


class SqlRepositorioDePedidos:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def criar(self, pedido: PedidoDeRelatorio) -> None:
        # Só o pedido novo é gravado aqui; as outras colunas mudam pelas transições abaixo.
        if pedido.status is not StatusDoPedido.PENDENTE:
            raise ValueError("Só um pedido pendente é criado.")
        await self._session.execute(
            insert(report_jobs).values(
                id=pedido.id,
                report_type=pedido.tipo.value,
                format=pedido.formato.value,
                filters=_json(pedido.filtros),
                requested_by=pedido.solicitado_por,
                scope_snapshot=_json(pedido.escopo),
                status=pedido.status.value,
                created_at=pedido.criado_em,
                updated_at=pedido.atualizado_em,
            )
        )

    async def obter(self, pedido_id: UUID) -> PedidoDeRelatorio | None:
        resultado = await self._session.execute(select(report_jobs).where(_t.id == pedido_id))
        linha = resultado.mappings().one_or_none()
        return None if linha is None else _pedido(linha)

    async def marcar_gerando(self, pedido_id: UUID, agora: datetime) -> bool:
        return await self._mudar(
            pedido_id,
            de=(StatusDoPedido.PENDENTE,),
            status=StatusDoPedido.GERANDO.value,
            started_at=agora,
            updated_at=agora,
        )

    async def concluir(self, pedido_id: UUID, conclusao: Conclusao, agora: datetime) -> bool:
        return await self._mudar(
            pedido_id,
            de=(StatusDoPedido.GERANDO,),
            status=StatusDoPedido.CONCLUIDO.value,
            storage_bucket=conclusao.bucket,
            storage_key=conclusao.chave,
            storage_version_id=conclusao.versao,
            size_bytes=conclusao.tamanho_bytes,
            sha256=conclusao.sha256,
            signature=conclusao.assinatura.valor,
            signature_alg=conclusao.assinatura.algoritmo,
            signature_kid=conclusao.assinatura.kid,
            finished_at=agora,
            expires_at=conclusao.vence_em,
            updated_at=agora,
        )

    async def falhar(self, pedido_id: UUID, erro: str, agora: datetime) -> bool:
        return await self._mudar(
            pedido_id,
            de=STATUS_ABERTOS,
            status=StatusDoPedido.FALHOU.value,
            # A coluna guarda até 200 caracteres: a falha não pode falhar por causa da mensagem.
            error=erro[:ERRO_MAX],
            finished_at=agora,
            updated_at=agora,
        )

    async def marcar_interrompidos(self, agora: datetime) -> tuple[UUID, ...]:
        resultado = await self._session.execute(
            update(report_jobs)
            .where(_t.status.in_([s.value for s in STATUS_ABERTOS]))
            .values(
                status=StatusDoPedido.FALHOU.value,
                error=ERRO_INTERROMPIDO,
                finished_at=agora,
                updated_at=agora,
            )
            .returning(_t.id)
        )
        return tuple(resultado.scalars().all())

    async def listar(
        self, *, solicitado_por: UUID | None, status: StatusDoPedido | None, pagina: Pagina
    ) -> tuple[list[PedidoDeRelatorio], int]:
        condicoes = []
        if solicitado_por is not None:
            condicoes.append(_t.requested_by == solicitado_por)
        if status is not None:
            condicoes.append(_t.status == status.value)
        total = await self._session.scalar(
            select(func.count()).select_from(report_jobs).where(*condicoes)
        )
        resultado = await self._session.execute(
            select(report_jobs)
            .where(*condicoes)
            .order_by(_t.created_at.desc(), _t.id.desc())
            .limit(pagina.tamanho)
            .offset(pagina.offset)
        )
        return [_pedido(linha) for linha in resultado.mappings()], int(total or 0)

    async def _mudar(
        self, pedido_id: UUID, *, de: tuple[StatusDoPedido, ...], **valores: Any
    ) -> bool:
        """UPDATE só se o status atual estiver em `de`; `False` se nenhuma linha mudou."""
        resultado = await self._session.execute(
            update(report_jobs)
            .where(_t.id == pedido_id, _t.status.in_([s.value for s in de]))
            .values(**valores)
            .returning(_t.id)
        )
        return resultado.scalar_one_or_none() is not None


def _json(valor: Mapping[str, object]) -> Any:
    """Forma JSON dos filtros e do escopo: tupla vira lista; UUID e data viram texto. Quem lê o
    pedido reconstrói os tipos (o escopo gravado, por exemplo)."""
    return json.loads(json.dumps(dict(valor), default=_como_texto))


def _como_texto(valor: object) -> str:
    if isinstance(valor, UUID):
        return str(valor)
    if isinstance(valor, date):  # inclui datetime
        return valor.isoformat()
    raise TypeError(f"Valor sem forma JSON no pedido de relatório: {type(valor).__name__}")


def _pedido(linha: RowMapping) -> PedidoDeRelatorio:
    assinatura = (
        None
        if linha["signature"] is None
        else Assinatura(
            kid=linha["signature_kid"],
            algoritmo=linha["signature_alg"],
            valor=linha["signature"],
        )
    )
    return PedidoDeRelatorio(
        id=linha["id"],
        tipo=TipoDeRelatorio(linha["report_type"]),
        formato=FormatoDeRelatorio(linha["format"]),
        filtros=linha["filters"],
        solicitado_por=linha["requested_by"],
        escopo=linha["scope_snapshot"],
        status=StatusDoPedido(linha["status"]),
        criado_em=linha["created_at"],
        atualizado_em=linha["updated_at"],
        iniciado_em=linha["started_at"],
        terminado_em=linha["finished_at"],
        vence_em=linha["expires_at"],
        bucket=linha["storage_bucket"],
        chave=linha["storage_key"],
        versao=linha["storage_version_id"],
        tamanho_bytes=linha["size_bytes"],
        sha256=linha["sha256"],
        assinatura=assinatura,
        erro=linha["error"],
    )
