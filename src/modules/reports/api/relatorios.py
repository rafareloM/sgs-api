"""Rotas dos relatórios (spec 005/T6; design § Rotas).

- `POST /relatorios` grava o pedido na transação da requisição, confirmada antes da resposta, e
  agenda a geração em segundo plano (R1.1).
- `GET /relatorios`, `GET /relatorios/{id}` e `GET /relatorios/{id}/download` (R3.1 a R3.5).

Consulta e listagem exigem `relatorio:export`; o download, `relatorio:download` (D005-11). Sem
`S3_BUCKET`, a exportação fica desligada: o pedido e o download respondem 503.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated, Any, Literal, Self
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from src.core.errors import ServiceUnavailable
from src.core.paginacao import TAMANHO_PADRAO, NumeroDaPagina, PaginaOut, TamanhoDaPagina
from src.core.problem import PROBLEM_JSON
from src.modules.access.api.deps import (
    SessaoDeNegocio,
    UsuarioAtual,
    ator_da_requisicao,
    require,
)
from src.modules.reports.application import pedidos as casos
from src.modules.reports.application.gerar import (
    Geracao,
    RepositoriosDoRelatorio,
    Transacoes,
    gerar_relatorio,
)
from src.modules.reports.domain.filtros import FiltrosDaTrilha, FiltrosDoInventario
from src.modules.reports.domain.pedidos import (
    FormatoDeRelatorio,
    Pagina,
    PedidoDeRelatorio,
    StatusDoPedido,
    TipoDeRelatorio,
)

router = APIRouter(prefix="/api/v1/relatorios", tags=["relatórios"])


def _problema(descricao: str) -> dict[str, Any]:
    return {"description": descricao, "content": {PROBLEM_JSON: {}}}


_401 = _problema("Sem access token válido")
_404 = _problema("Relatório inexistente")
_503 = _problema("Exportação não configurada (sem `S3_BUCKET`)")
QuemExporta = Annotated[UsuarioAtual, Depends(require(casos.PERMISSAO_DE_EXPORTAR))]
QuemBaixa = Annotated[UsuarioAtual, Depends(require(casos.PERMISSAO_DE_BAIXAR))]

_CONFIG = ConfigDict(extra="forbid")


class PedidoDoInventarioIn(BaseModel):
    model_config = _CONFIG

    tipo: Literal["inventario_unidades"]
    formato: Literal["csv", "xlsx"]
    filtros: FiltrosDoInventario = FiltrosDoInventario()


class PedidoDaTrilhaIn(BaseModel):
    model_config = _CONFIG

    tipo: Literal["trilha_auditoria"]
    formato: Literal["csv", "xlsx"]
    filtros: FiltrosDaTrilha


PedidoIn = Annotated[PedidoDoInventarioIn | PedidoDaTrilhaIn, Field(discriminator="tipo")]


class PedidoCriadoOut(BaseModel):
    id: UUID
    status: Literal["pendente"] = "pendente"


class IntegridadeOut(BaseModel):
    """R5.3: o hash do arquivo e a assinatura, para conferir fora da API (R5.4)."""

    sha256: str
    assinatura: str
    algoritmo: str
    kid: str


class RelatorioOut(BaseModel):
    id: UUID
    tipo: TipoDeRelatorio
    formato: FormatoDeRelatorio
    filtros: dict[str, Any]
    status: StatusDoPedido
    solicitado_por: UUID
    criado_em: datetime
    concluido_em: datetime | None
    tamanho_bytes: int | None
    vence_em: datetime | None
    vencido: bool
    erro: str | None
    integridade: IntegridadeOut | None

    @classmethod
    def de(cls, p: PedidoDeRelatorio, agora: datetime) -> Self:
        concluido = p.status is StatusDoPedido.CONCLUIDO
        integridade = None
        if concluido and p.sha256 is not None and p.assinatura is not None:
            integridade = IntegridadeOut(
                sha256=p.sha256,
                assinatura=p.assinatura.valor,
                algoritmo=p.assinatura.algoritmo,
                kid=p.assinatura.kid,
            )
        return cls(
            id=p.id,
            tipo=p.tipo,
            formato=p.formato,
            filtros=dict(p.filtros),
            status=p.status,
            solicitado_por=p.solicitado_por,
            criado_em=p.criado_em,
            concluido_em=p.terminado_em if concluido else None,
            tamanho_bytes=p.tamanho_bytes,
            vence_em=p.vence_em,
            vencido=casos.vencido(p, agora),
            erro=p.erro,
            integridade=integridade,
        )


class DownloadOut(BaseModel):
    """D005-1: a URL pré-assinada é uma credencial de 5 minutos (`no-store`)."""

    url: str
    expira_em: datetime


def _agora() -> datetime:
    return datetime.now(UTC)


def _geracao(request: Request) -> Geracao:
    geracao: Geracao | None = request.app.state.geracao_de_relatorios
    if geracao is None:
        raise ServiceUnavailable("Exportação de relatórios não configurada.")
    return geracao


@router.post(
    "",
    status_code=202,
    summary="Pedir um relatório",
    responses={
        401: _401,
        403: _problema("Sem `relatorio:export` ou sem a permissão de dados do tipo"),
        422: _problema("Tipo, formato ou filtros inválidos"),
        503: _503,
    },
)
async def pedir(
    request: Request,
    tarefas: BackgroundTasks,
    corpo: PedidoIn,
    usuario: QuemExporta,
    sessao: SessaoDeNegocio,
) -> PedidoCriadoOut:
    """R1.1 a R1.5: 202 com o id; a geração segue em segundo plano. `inventario_unidades` exige
    `unidade:read`; `trilha_auditoria`, `auditoria:read`."""
    geracao = _geracao(request)
    estado = request.app.state
    ator = ator_da_requisicao(request, usuario)
    pedido = await casos.solicitar(
        usuario,
        tipo=TipoDeRelatorio(corpo.tipo),
        formato=FormatoDeRelatorio(corpo.formato),
        filtros=corpo.filtros,
        pedidos=estado.repositorio_de_pedidos(sessao),
        referencias=estado.referencias_dos_filtros(sessao),
        auditoria=estado.auditoria(sessao),
        ator=ator,
        gerar_id=estado.gerar_id,
        agora=_agora,
    )
    # A sessão da requisição confirma antes de a resposta sair; a tarefa acha o pedido.
    tarefas.add_task(gerar_relatorio, pedido.id, geracao=geracao, ator=ator)
    return PedidoCriadoOut(id=pedido.id)


@router.get(
    "",
    summary="Relatórios pedidos",
    responses={401: _401, 403: _problema("Sem `relatorio:export`")},
)
async def listar(
    request: Request,
    usuario: QuemExporta,
    sessao: SessaoDeNegocio,
    status: Annotated[StatusDoPedido | None, Query()] = None,
    pagina: NumeroDaPagina = 1,
    tamanho: TamanhoDaPagina = TAMANHO_PADRAO,
) -> PaginaOut[RelatorioOut]:
    """R3.5: do mais recente ao mais antigo; os do usuário, ou todos para `GESTOR_DADOS`."""
    itens, total = await casos.listar(
        usuario,
        status=status,
        pagina=Pagina(numero=pagina, tamanho=tamanho),
        pedidos=request.app.state.repositorio_de_pedidos(sessao),
    )
    agora = _agora()
    return PaginaOut(
        itens=[RelatorioOut.de(p, agora) for p in itens],
        total=total,
        pagina=pagina,
        tamanho=tamanho,
    )


@router.get(
    "/{id_}",
    summary="Um relatório",
    responses={
        401: _401,
        403: _problema("Nem quem pediu, nem escopo que cubra o do pedido"),
        404: _404,
    },
)
async def consultar(
    request: Request, id_: UUID, usuario: QuemExporta, sessao: SessaoDeNegocio
) -> RelatorioOut:
    """R3.1, R3.3, R5.3: status, e `integridade` quando concluído."""
    visivel = await casos.obter(
        usuario,
        id_,
        pedidos=request.app.state.repositorio_de_pedidos(sessao),
        permissao=casos.PERMISSAO_DE_EXPORTAR,
    )
    return RelatorioOut.de(visivel.pedido, _agora())


@router.get(
    "/{id_}/download",
    summary="URL de download de um relatório",
    responses={
        401: _401,
        403: _problema("Sem `relatorio:download`, ou nem quem pediu nem escopo que cubra"),
        404: _404,
        409: _problema("Relatório não concluído ou vencido"),
        503: _503,
    },
)
async def baixar(
    request: Request,
    response: Response,
    id_: UUID,
    usuario: QuemBaixa,
    sessao: SessaoDeNegocio,
) -> DownloadOut:
    """R3.2 a R3.4, R3.6: 200 com a URL de 5 minutos no endereço público; `no-store`."""
    geracao = _geracao(request)
    estado = request.app.state
    url = await casos.baixar(
        usuario,
        id_,
        pedidos=estado.repositorio_de_pedidos(sessao),
        armazenamento=geracao.armazenamento,
        auditoria=estado.auditoria(sessao),
        ator=ator_da_requisicao(request, usuario),
        agora=_agora,
    )
    response.headers["Cache-Control"] = "no-store"
    return DownloadOut(url=url.url, expira_em=url.expira_em)


def transacoes_dos_relatorios(estado: Any) -> Transacoes:
    """Uma transação por chamada do caso de uso da geração, com os repositórios sobre a mesma
    sessão: confirma na saída, ou desfaz se uma exceção passar."""

    @asynccontextmanager
    async def abrir() -> AsyncIterator[RepositoriosDoRelatorio]:
        async with estado.sessoes() as sessao, sessao.begin():
            yield RepositoriosDoRelatorio(
                pedidos=estado.repositorio_de_pedidos(sessao), auditoria=estado.auditoria(sessao)
            )

    return abrir
