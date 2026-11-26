"""Pedido, consulta, listagem e download dos relatórios (spec 005/T6; design § Rotas, § Escopo
dos relatórios e § Fluxo, Pedido e Download).

- O pedido exige a permissão de dados do tipo (`unidade:read` ou `auditoria:read`, D005-12): sem
  ela, 403 (R1.4). O escopo gravado é o `EscopoLeitura` dessa permissão (R1.3).
- Consulta e download valem para quem pediu, ou para quem tem, na mesma permissão de dados, um
  escopo que cubra o gravado (`escopo_cobre`, R3.3).
- A listagem traz os pedidos do usuário; com o papel `GESTOR_DADOS`, os de todos (R3.5).
- O download audita `relatorio.baixado` com o vencimento da URL e nunca com a URL (R3.4).
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, Protocol
from uuid import UUID

from src.core.errors import Conflict, DomainValidationError, FieldError, NotFound
from src.modules.access.application.autorizacao import (
    AcessoNegado,
    Ator,
    AuditStore,
    Entidade,
    UsuarioAtual,
    escopo_de_leitura,
)
from src.modules.audit.application.registrar import registrar
from src.modules.reports.domain.armazenamento import (
    ArmazenamentoDeObjetos,
    UrlAssinada,
    nome_do_arquivo,
)
from src.modules.reports.domain.escopo import escopo_cobre, escopo_gravado, escopo_para_gravar
from src.modules.reports.domain.filtros import Filtros, FiltrosDoInventario
from src.modules.reports.domain.pedidos import (
    FormatoDeRelatorio,
    Pagina,
    PedidoDeRelatorio,
    StatusDoPedido,
    TipoDeRelatorio,
    novo_pedido,
)
from src.modules.reports.domain.ports import RepositorioDePedidos

PERMISSAO_DE_DADOS: Final[Mapping[TipoDeRelatorio, str]] = {
    TipoDeRelatorio.INVENTARIO_UNIDADES: "unidade:read",
    TipoDeRelatorio.TRILHA_AUDITORIA: "auditoria:read",
}
"""D005-12: o escopo do relatório é o de leitura da permissão de dados do tipo."""

PERMISSAO_DE_EXPORTAR: Final = "relatorio:export"
PERMISSAO_DE_BAIXAR: Final = "relatorio:download"
PAPEL_QUE_VE_TODOS: Final = "GESTOR_DADOS"  # R3.5
ENTIDADE: Final = "relatorio"


class ReferenciasDosFiltros(Protocol):
    """Confere os ids dos filtros do inventário contra as referências da 006 (422, R1.5)."""

    async def inexistentes(self, filtros: FiltrosDoInventario) -> list[str]:
        """Os campos de `filtros` com id que não existe."""
        ...


@dataclass(frozen=True)
class Visivel:
    """O pedido que o usuário pode ver, e se é dele."""

    pedido: PedidoDeRelatorio
    proprio: bool


async def solicitar(
    usuario: UsuarioAtual,
    *,
    tipo: TipoDeRelatorio,
    formato: FormatoDeRelatorio,
    filtros: Filtros,
    pedidos: RepositorioDePedidos,
    referencias: ReferenciasDosFiltros,
    auditoria: AuditStore,
    ator: Ator,
    gerar_id: Callable[[], UUID],
    agora: Callable[[], datetime],
) -> PedidoDeRelatorio:
    """Grava o pedido `pendente` com o escopo de quem pediu e audita `relatorio.solicitado`
    (design § Fluxo, Pedido, passos 2 a 4). Quem chama agenda a geração depois de confirmar."""
    permissao = PERMISSAO_DE_DADOS[tipo]
    escopo = escopo_de_leitura(usuario, permissao)
    if not (escopo.global_ or escopo.areas or escopo.distritos or escopo.unidades):
        raise AcessoNegado(permissao)  # R1.4
    if isinstance(filtros, FiltrosDoInventario):
        campos = await referencias.inexistentes(filtros)
        if campos:
            raise DomainValidationError(
                "Filtro com referência inexistente.",
                [FieldError(campo=f"filtros.{c}", mensagem="Não existe.") for c in campos],
            )
    pedido = novo_pedido(
        id=gerar_id(),
        tipo=tipo,
        formato=formato,
        filtros=filtros.model_dump(mode="json"),
        solicitado_por=usuario.id,
        escopo=escopo_para_gravar(escopo),
        agora=agora(),
    )
    await pedidos.criar(pedido)
    await registrar(
        auditoria,
        acao="relatorio.solicitado",
        ator=ator,
        entidade=Entidade(tipo=ENTIDADE, id=str(pedido.id)),
        metadados={"tipo": str(tipo), "formato": str(formato)},
    )
    return pedido


async def obter(
    usuario: UsuarioAtual, pedido_id: UUID, *, pedidos: RepositorioDePedidos, permissao: str
) -> Visivel:
    """404 se não existe; 403 se não é de quem pede nem coberto pelo escopo dele (R3.3)."""
    pedido = await pedidos.obter(pedido_id)
    if pedido is None:
        raise NotFound("Relatório não encontrado.")
    if pedido.solicitado_por == usuario.id:
        return Visivel(pedido, proprio=True)
    try:
        gravado = escopo_gravado(pedido.escopo)
    except ValueError:
        raise AcessoNegado(permissao) from None  # fora do formato: falha fechado
    if not escopo_cobre(escopo_de_leitura(usuario, PERMISSAO_DE_DADOS[pedido.tipo]), gravado):
        raise AcessoNegado(permissao)
    return Visivel(pedido, proprio=False)


async def listar(
    usuario: UsuarioAtual,
    *,
    status: StatusDoPedido | None,
    pagina: Pagina,
    pedidos: RepositorioDePedidos,
) -> tuple[list[PedidoDeRelatorio], int]:
    """R3.5: os do usuário; com `GESTOR_DADOS`, os de todos."""
    solicitado_por = None if PAPEL_QUE_VE_TODOS in usuario.papeis else usuario.id
    return await pedidos.listar(solicitado_por=solicitado_por, status=status, pagina=pagina)


def vencido(pedido: PedidoDeRelatorio, agora: datetime) -> bool:
    return pedido.vence_em is not None and pedido.vence_em <= agora


async def baixar(
    usuario: UsuarioAtual,
    pedido_id: UUID,
    *,
    pedidos: RepositorioDePedidos,
    armazenamento: ArmazenamentoDeObjetos,
    auditoria: AuditStore,
    ator: Ator,
    agora: Callable[[], datetime],
) -> UrlAssinada:
    """URL de 5 minutos para quem pode (design § Fluxo, Download, passos 1 a 5)."""
    visivel = await obter(usuario, pedido_id, pedidos=pedidos, permissao=PERMISSAO_DE_BAIXAR)
    pedido = visivel.pedido
    if pedido.status is not StatusDoPedido.CONCLUIDO or pedido.chave is None:
        raise Conflict("O relatório ainda não está pronto.")
    if vencido(pedido, agora()):
        raise Conflict("O relatório venceu e não pode mais ser baixado.")
    url = await armazenamento.url_de_download(
        pedido.chave,
        nome=nome_do_arquivo(
            tipo=str(pedido.tipo),
            data=pedido.criado_em.astimezone(UTC).date(),
            formato=str(pedido.formato),
        ),
        sessao=str(usuario.id),  # R2.1: `sgs-{id}` de quem baixa
    )
    await registrar(
        auditoria,
        acao="relatorio.baixado",
        ator=ator,
        entidade=Entidade(tipo=ENTIDADE, id=str(pedido.id)),
        metadados={"expira_em": url.expira_em.isoformat()},  # R3.4: nunca a URL
    )
    return url
