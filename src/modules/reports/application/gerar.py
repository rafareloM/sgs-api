"""Geração e envio de um relatório (spec 005/T5; design § Fluxo, Geração e envio, passos 1 a 8).

1. `gerando` só se o pedido estiver `pendente`, numa transação curta (passo 1).
2. As linhas saem das consultas (T11) no escopo gravado no pedido, nunca no escopo do momento
   (R1.3), e vão para um temporário em disco, com o SHA-256 calculado durante a escrita (passo 2).
3. O hash é assinado com a chave de relatórios (R5.1, passo 3).
4. O envio usa a sessão de quem pediu (`sgs-{id}`, R2.1) e o que o armazenamento informou é
   conferido; se não conferir, a versão gravada é removida (R2.8, passos 4 e 5).
5. A conclusão grava hash, assinatura e vencimento e audita `relatorio.exportado` (R2.5, passo 6).
6. Qualquer falha vira `falhou` com mensagem genérica, numa transação própria (R2.6, passo 7).
7. Na subida, pedidos `pendente` e `gerando` viram `falhou` com "Interrompido" (passo 8).

A escrita do arquivo é bloqueante (`csv` e `openpyxl`): cada lote vai a `em_thread`, que a raiz
de composição liga a `anyio.to_thread.run_sync`.
"""

import base64
import functools
import logging
import tempfile
from collections.abc import Awaitable, Callable, Mapping
from contextlib import AbstractAsyncContextManager, aclosing
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import BinaryIO, Final
from uuid import UUID

from src.modules.audit.application.registrar import Ator, AuditStore, Entidade, registrar
from src.modules.reports.domain.armazenamento import (
    ArmazenamentoDeObjetos,
    GravacaoEsperada,
    ObjetoGravado,
    Sse,
    chave_do_objeto,
    conferir_gravacao,
    tipo_de_conteudo,
)
from src.modules.reports.domain.arquivo import (
    MENSAGEM_GRANDE_DEMAIS,
    ArquivoGerado,
    GeradorDeArquivo,
    RelatorioGrandeDemais,
)
from src.modules.reports.domain.assinatura import AssinadorDeRelatorio, Assinatura
from src.modules.reports.domain.colunas import COLUNAS_POR_TIPO, Coluna
from src.modules.reports.domain.escopo import escopo_gravado
from src.modules.reports.domain.filtros import MODELO_DOS_FILTROS
from src.modules.reports.domain.pedidos import ERRO_INTERROMPIDO, Conclusao, PedidoDeRelatorio
from src.modules.reports.domain.ports import ConsultasDeRelatorio, RepositorioDePedidos

ACAO_EXPORTADO: Final = "relatorio.exportado"
ENTIDADE: Final = "relatorio"
ERRO_GERAL: Final = "Não foi possível gerar ou enviar o relatório"
TAMANHO_EM_MEMORIA: Final = 20 * 1024 * 1024  # design § Geração e envio, passo 2
# A subida da API fecha o que ficou em andamento: é o próprio sistema, não uma pessoa.
ATOR_DA_SUBIDA: Final = Ator(tipo="sistema", origem="api")

_log = logging.getLogger("sgs_api.relatorios")


@dataclass(frozen=True)
class RepositoriosDoRelatorio:
    """Os repositórios de uma transação, sobre a mesma sessão."""

    pedidos: RepositorioDePedidos
    auditoria: AuditStore


type Transacoes = Callable[[], AbstractAsyncContextManager[RepositoriosDoRelatorio]]
type NovoGerador = Callable[[str, BinaryIO, tuple[Coluna, ...]], GeradorDeArquivo]
type EmThread = Callable[[Callable[[], object]], Awaitable[object]]


@dataclass(frozen=True)
class Destino:
    """Para onde vai o arquivo e o que a gravação tem de informar (R2.3, R2.8; § Configuração)."""

    bucket: str
    sse: Sse
    kms_key_id: str | None
    retencao: timedelta  # REPORT_RETENTION_DAYS: `expires_at = finished_at + retenção`


@dataclass(frozen=True)
class Geracao:
    """As peças da geração, montadas na raiz de composição."""

    transacoes: Transacoes
    consultas: ConsultasDeRelatorio
    armazenamento: ArmazenamentoDeObjetos
    assinador: AssinadorDeRelatorio
    novo_gerador: NovoGerador
    em_thread: EmThread
    destino: Destino
    agora: Callable[[], datetime]


class GravacaoNaoConfere(Exception):  # noqa: N818 (sinal interno, vira a mensagem genérica)
    def __init__(self, campos: list[str]) -> None:
        super().__init__(f"gravação não confere: {', '.join(campos)}")


async def gerar_relatorio(pedido_id: UUID, *, geracao: Geracao, ator: Ator) -> None:
    """Gera, assina, envia e conclui o pedido. Nunca levanta: na falha, o pedido fica `falhou`.

    `ator` é quem pediu (a auditoria de `relatorio.exportado` é dele, R2.5)."""
    async with geracao.transacoes() as repos:
        if not await repos.pedidos.marcar_gerando(pedido_id, geracao.agora()):
            return  # outro já começou, ou o pedido não está pendente (passo 1)
        pedido = await repos.pedidos.obter(pedido_id)
    if pedido is None:  # pragma: no cover - acabou de ser marcado na mesma transação
        return

    try:
        await _gerar_e_enviar(pedido, geracao, ator)
    except RelatorioGrandeDemais:
        _log.warning("relatório %s não gerado: grande demais", pedido_id)
        await _falhou(pedido, MENSAGEM_GRANDE_DEMAIS, geracao=geracao, ator=ator)
    except Exception as erro:
        # Só o tipo do erro: a mensagem do SDK pode citar a URL ou a chave do objeto.
        _log.error("relatório %s não gerado: %s", pedido_id, type(erro).__name__)
        await _falhou(pedido, ERRO_GERAL, geracao=geracao, ator=ator)


async def marcar_interrompidos(*, transacoes: Transacoes, agora: Callable[[], datetime]) -> int:
    """Na subida, `pendente` e `gerando` viram `falhou` com "Interrompido" (passo 8). A API roda
    numa instância só (design § Riscos), então nenhum deles está vivo."""
    async with transacoes() as repos:
        ids = await repos.pedidos.marcar_interrompidos(agora())
        for pedido_id in ids:
            await _auditar(
                repos.auditoria,
                pedido_id,
                ATOR_DA_SUBIDA,
                metadados={"erro": ERRO_INTERROMPIDO},
                resultado="failure",
            )
    return len(ids)


async def _gerar_e_enviar(pedido: PedidoDeRelatorio, geracao: Geracao, ator: Ator) -> None:
    tipo, formato = str(pedido.tipo), str(pedido.formato)
    filtros = MODELO_DOS_FILTROS[pedido.tipo.value].model_validate(pedido.filtros)
    escopo = escopo_gravado(pedido.escopo)  # R1.3: só o escopo do pedido
    sessao = str(pedido.solicitado_por)  # R2.1: `sgs-{id}` de quem pediu

    with tempfile.SpooledTemporaryFile(max_size=TAMANHO_EM_MEMORIA) as arquivo:
        destino: BinaryIO = arquivo  # type: ignore[assignment]
        gerador = geracao.novo_gerador(formato, destino, COLUNAS_POR_TIPO[tipo])
        try:
            async with aclosing(geracao.consultas.lotes(tipo, filtros, escopo)) as lotes:
                async for lote in lotes:
                    await geracao.em_thread(functools.partial(gerador.escrever, lote))
            gerado = await geracao.em_thread(gerador.finalizar)
        finally:
            gerador.descartar()
        if not isinstance(gerado, ArquivoGerado):  # pragma: no cover - `finalizar` devolve
            raise TypeError("o gerador não devolveu o arquivo gerado")

        assinatura = geracao.assinador.assinar(gerado.sha256)  # R5.1
        sha256_b64 = base64.b64encode(gerado.sha256).decode("ascii")
        destino.seek(0)
        gravado = await geracao.armazenamento.enviar(
            chave_do_objeto(
                criado_em=pedido.criado_em, tipo=tipo, pedido_id=pedido.id, formato=formato
            ),
            destino,
            content_type=tipo_de_conteudo(formato),
            sha256_b64=sha256_b64,
            metadados=_metadados_do_objeto(gerado, assinatura),
            sessao=sessao,
        )
    await _conferir(gravado, sha256_b64, geracao, sessao)

    agora = geracao.agora()
    conclusao = Conclusao(
        bucket=geracao.destino.bucket,
        chave=gravado.key,
        versao=gravado.version_id,
        tamanho_bytes=gerado.tamanho,
        sha256=gerado.sha256.hex(),
        assinatura=assinatura,
        vence_em=agora + geracao.destino.retencao,
    )
    async with geracao.transacoes() as repos:
        if not await repos.pedidos.concluir(pedido.id, conclusao, agora):
            # Fechado por outra via enquanto gerava (a subida o marcou como interrompido): o
            # objeto não fica no armazenamento sem um pedido que o aponte.
            _log.warning("relatório %s fechado durante a geração", pedido.id)
            await geracao.armazenamento.remover(gravado.key, gravado.version_id, sessao=sessao)
            return
        await _auditar(
            repos.auditoria,
            pedido.id,
            ator,
            metadados={
                "tipo": tipo,
                "formato": formato,
                "tamanho_bytes": gerado.tamanho,
                "sha256": conclusao.sha256,
                "kid": assinatura.kid,
            },
            resultado="success",
        )


async def _conferir(gravado: ObjetoGravado, sha256_b64: str, geracao: Geracao, sessao: str) -> None:
    """R2.8: confere o que o armazenamento informou; se não conferir, remove a versão gravada."""
    esperada = GravacaoEsperada(
        sse=geracao.destino.sse, kms_key_id=geracao.destino.kms_key_id, sha256_b64=sha256_b64
    )
    problemas = conferir_gravacao(esperada, gravado)
    if problemas:
        await geracao.armazenamento.remover(gravado.key, gravado.version_id, sessao=sessao)
        raise GravacaoNaoConfere(problemas)


def _metadados_do_objeto(gerado: ArquivoGerado, assinatura: Assinatura) -> Mapping[str, str]:
    """Hash e assinatura também no objeto, para quem baixa direto do armazenamento (§ Envio)."""
    return {
        "sgs-sha256": gerado.sha256.hex(),
        "sgs-kid": assinatura.kid,
        "sgs-assinatura": assinatura.valor,
    }


async def _falhou(pedido: PedidoDeRelatorio, erro: str, *, geracao: Geracao, ator: Ator) -> None:
    try:
        async with geracao.transacoes() as repos:
            if await repos.pedidos.falhar(pedido.id, erro, geracao.agora()):
                await _auditar(
                    repos.auditoria,
                    pedido.id,
                    ator,
                    metadados={"erro": erro},
                    resultado="failure",
                )
    except Exception as falha:
        # Não deixa a tarefa em segundo plano morrer com exceção. O pedido fica `gerando` até a
        # próxima subida da API, que o fecha como "Interrompido" (passo 8).
        _log.error("relatório %s não foi fechado: %s", pedido.id, type(falha).__name__)


async def _auditar(
    auditoria: AuditStore,
    pedido_id: UUID,
    ator: Ator,
    *,
    metadados: Mapping[str, object],
    resultado: str,
) -> None:
    await registrar(
        auditoria,
        acao=ACAO_EXPORTADO,
        ator=ator,
        entidade=Entidade(tipo=ENTIDADE, id=str(pedido_id)),
        metadados=metadados,
        resultado=resultado,
        categoria="erro_interno" if resultado == "failure" else None,
    )
