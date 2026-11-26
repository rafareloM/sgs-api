"""Caso de uso da geração e do envio sobre o PostgreSQL, com armazenamento falso (005/T5).

Design da 005 § Fluxo, Geração e envio, passos 1 a 8. As consultas (T11), os geradores (T2) e
o assinador (T9) são os de produção; só o S3 é trocado por um falso que guarda o que recebe e
responde o que o teste mandar.
"""

import base64
import hashlib
import json
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from io import BytesIO
from typing import Any, BinaryIO
from uuid import UUID

import anyio.to_thread
import httpx
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import Prehashed, encode_dss_signature
from fastapi import FastAPI
from openpyxl import load_workbook
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from src.core.ids import uuid7
from src.modules.audit.application.registrar import Ator
from src.modules.audit.infrastructure.repository import SqlAuditStore
from src.modules.identity.infrastructure.repository import SqlUserRepository
from src.modules.reports.application.gerar import (
    ERRO_GERAL,
    Destino,
    Geracao,
    RepositoriosDoRelatorio,
    gerar_relatorio,
    marcar_interrompidos,
)
from src.modules.reports.domain.arquivo import MENSAGEM_GRANDE_DEMAIS, GeradorDeArquivo
from src.modules.reports.domain.colunas import Coluna
from src.modules.reports.domain.escopo import EscopoGravado, escopo_para_gravar
from src.modules.reports.domain.pedidos import (
    ERRO_INTERROMPIDO,
    FormatoDeRelatorio,
    PedidoDeRelatorio,
    StatusDoPedido,
    TipoDeRelatorio,
    novo_pedido,
)
from src.modules.reports.infrastructure.assinatura import Es256AssinadorDeRelatorio
from src.modules.reports.infrastructure.consultas import SqlConsultasDeRelatorio
from src.modules.reports.infrastructure.generators import novo_gerador
from src.modules.reports.infrastructure.repository import SqlRepositorioDePedidos
from tests.factories import make_jwt_private_keys, make_settings, make_user
from tests.integration.acesso import GLOBAL, Sessoes, bearer, id_pelo_codigo, logado
from tests.integration.postgres import BancoDeTeste, motor
from tests.integration.reports.falsos import ArmazenamentoFalso

BUCKET = "sgs-relatorios"
ESCOPO_GLOBAL = EscopoGravado(global_=True)


@pytest.fixture
async def engine(banco: BancoDeTeste) -> AsyncIterator[AsyncEngine]:
    """Com o login da API (papel sgs_app), como em produção."""
    motor_da_api = motor(banco.url_api)
    yield motor_da_api
    await motor_da_api.dispose()


@pytest.fixture
def assinador() -> Es256AssinadorDeRelatorio:
    settings = make_settings(report_signing_keys=make_jwt_private_keys("rel-2026-11-26"))
    assinador = Es256AssinadorDeRelatorio.from_settings(settings)
    assert assinador is not None
    return assinador


@pytest.fixture
def armazenamento() -> ArmazenamentoFalso:
    return ArmazenamentoFalso()


def _transacoes(sessoes: Sessoes) -> Any:
    @asynccontextmanager
    async def abrir() -> AsyncIterator[RepositoriosDoRelatorio]:
        async with sessoes() as sessao, sessao.begin():
            yield RepositoriosDoRelatorio(
                pedidos=SqlRepositorioDePedidos(sessao), auditoria=SqlAuditStore(sessao)
            )

    return abrir


async def _em_thread(chamada: Any) -> object:
    return await anyio.to_thread.run_sync(chamada)


def _geracao(
    sessoes: Sessoes,
    engine: AsyncEngine,
    armazenamento: ArmazenamentoFalso,
    assinador: Es256AssinadorDeRelatorio,
    **trocas: Any,
) -> Geracao:
    geracao = Geracao(
        transacoes=_transacoes(sessoes),
        consultas=SqlConsultasDeRelatorio(engine),
        armazenamento=armazenamento,
        assinador=assinador,
        novo_gerador=novo_gerador,
        em_thread=_em_thread,
        destino=Destino(bucket=BUCKET, sse="AES256", kms_key_id=None, retencao=timedelta(days=90)),
        agora=lambda: datetime.now(UTC),
    )
    return replace(geracao, **trocas)


@pytest.fixture
async def rede(app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes) -> dict[str, Any]:
    """Duas unidades em distritos diferentes, criadas pela API (com a trilha da criação)."""
    gestor = bearer(app, await logado(sessoes, ("GESTOR_DADOS", GLOBAL)))
    ds1 = await id_pelo_codigo(sessoes, "distrito", "DS-I")
    ds2 = await id_pelo_codigo(sessoes, "distrito", "DS-II")
    caps = await id_pelo_codigo(sessoes, "tipo_unidade", "CAPS_II")
    for nome, distrito, cnes in (("CAPS A", ds1, "1111111"), ("CAPS C", ds2, "3333333")):
        corpo = {
            "nome": nome,
            "tipo_unidade_id": caps,
            "distrito_id": distrito,
            "cep": "50010100",
            "endereco": "Rua A, 1",
            "status": "ativa",
            "cnes": cnes,
        }
        resposta = await cliente.post("/api/v1/unidades", json=corpo, headers=gestor)
        assert resposta.status_code == 201, resposta.text
    return {"ds1": ds1, "ds2": ds2}


async def _pedido(
    sessoes: Sessoes,
    *,
    tipo: TipoDeRelatorio = TipoDeRelatorio.INVENTARIO_UNIDADES,
    formato: FormatoDeRelatorio = FormatoDeRelatorio.CSV,
    filtros: Mapping[str, object] | None = None,
    escopo: EscopoGravado = ESCOPO_GLOBAL,
) -> tuple[PedidoDeRelatorio, Ator]:
    usuario = make_user(username=f"u{uuid7().hex}", email=None)
    pedido = novo_pedido(
        id=uuid7(),
        tipo=tipo,
        formato=formato,
        filtros=filtros or {},
        solicitado_por=usuario.id,
        escopo=escopo_para_gravar(escopo),
        agora=datetime.now(UTC),
    )
    async with sessoes() as sessao, sessao.begin():
        await SqlUserRepository(sessao).add(usuario)
        await SqlRepositorioDePedidos(sessao).criar(pedido)
    return pedido, Ator(user_id=usuario.id, papeis=("GESTOR_DADOS",), tipo="usuario")


async def _obter(sessoes: Sessoes, pedido_id: UUID) -> PedidoDeRelatorio:
    async with sessoes() as sessao:
        pedido = await SqlRepositorioDePedidos(sessao).obter(pedido_id)
    assert pedido is not None
    return pedido


async def _auditoria(sessoes: Sessoes, pedido_id: UUID) -> list[dict[str, Any]]:
    async with sessoes() as sessao:
        resultado = await sessao.execute(
            text(
                "SELECT actor_user_id, actor_type, result, metadata FROM audit_log"
                " WHERE action = 'relatorio.exportado' AND entity_type = 'relatorio'"
                " AND entity_id = :id ORDER BY id"
            ),
            {"id": str(pedido_id)},
        )
        return [dict(linha) for linha in resultado.mappings()]


def _confere_assinatura(assinador: Es256AssinadorDeRelatorio, sha256: bytes, valor: str) -> None:
    """Como quem recebe o arquivo: só com a JWK pública (R5.4)."""
    [jwk] = assinador.chaves_publicas()

    def inteiro(campo: str) -> int:
        return int.from_bytes(base64.urlsafe_b64decode(campo + "=" * (-len(campo) % 4)), "big")

    publica = ec.EllipticCurvePublicNumbers(inteiro(jwk.x), inteiro(jwk.y), ec.SECP256R1())
    assinatura = base64.urlsafe_b64decode(valor + "=" * (-len(valor) % 4))
    der = encode_dss_signature(
        int.from_bytes(assinatura[:32], "big"), int.from_bytes(assinatura[32:], "big")
    )
    publica.public_key().verify(der, sha256, ec.ECDSA(Prehashed(hashes.SHA256())))


async def test_concluido_com_hash_assinatura_vencimento_e_auditoria(
    sessoes: Sessoes,
    engine: AsyncEngine,
    armazenamento: ArmazenamentoFalso,
    assinador: Es256AssinadorDeRelatorio,
    rede: dict[str, Any],
) -> None:
    """005/R2.5, R5.1, R2.1, R2.4 (concluído com hash, assinatura e `expires_at`; envio com a
    sessão de quem pediu, na chave do pedido; `relatorio.exportado` com `success`)"""
    pedido, ator = await _pedido(sessoes)

    await gerar_relatorio(
        pedido.id, geracao=_geracao(sessoes, engine, armazenamento, assinador), ator=ator
    )

    concluido = await _obter(sessoes, pedido.id)
    [enviado] = armazenamento.enviados
    sha256 = hashlib.sha256(enviado["conteudo"]).digest()
    assert concluido.status is StatusDoPedido.CONCLUIDO
    assert concluido.sha256 == sha256.hex()
    assert concluido.tamanho_bytes == len(enviado["conteudo"])
    assert enviado["sha256_b64"] == base64.b64encode(sha256).decode()
    assert concluido.terminado_em is not None
    assert concluido.vence_em is not None
    assert concluido.vence_em - concluido.terminado_em == timedelta(days=90)
    assert (concluido.bucket, concluido.chave, concluido.versao) == (BUCKET, enviado["key"], "v-1")
    assert enviado["key"].startswith(f"reports/{pedido.criado_em:%Y/%m}/inventario_unidades/")
    assert enviado["key"].endswith(f"{pedido.id}.csv")
    assert enviado["sessao"] == str(pedido.solicitado_por)
    assert enviado["content_type"] == "text/csv; charset=utf-8"
    assert concluido.assinatura is not None
    assert enviado["metadados"] == {
        "sgs-sha256": sha256.hex(),
        "sgs-kid": concluido.assinatura.kid,
        "sgs-assinatura": concluido.assinatura.valor,
    }
    _confere_assinatura(assinador, sha256, concluido.assinatura.valor)
    texto = enviado["conteudo"].decode("utf-8-sig")
    assert "CAPS A" in texto
    assert "CAPS C" in texto
    [evento] = await _auditoria(sessoes, pedido.id)
    assert (evento["actor_user_id"], evento["result"]) == (pedido.solicitado_por, "success")
    assert evento["metadata"] == {
        "tipo": "inventario_unidades",
        "formato": "csv",
        "tamanho_bytes": len(enviado["conteudo"]),
        "sha256": sha256.hex(),
        "kid": concluido.assinatura.kid,
    }


async def test_gera_so_no_escopo_gravado(
    sessoes: Sessoes,
    engine: AsyncEngine,
    armazenamento: ArmazenamentoFalso,
    assinador: Es256AssinadorDeRelatorio,
    rede: dict[str, Any],
) -> None:
    """005/R1.3 (o escopo é o do pedido, em XLSX e na trilha restrita)"""
    agora = datetime.now(UTC)
    escopo = EscopoGravado(distritos=(rede["ds2"],))
    inventario, ator = await _pedido(sessoes, formato=FormatoDeRelatorio.XLSX, escopo=escopo)
    trilha, _ = await _pedido(
        sessoes,
        tipo=TipoDeRelatorio.TRILHA_AUDITORIA,
        filtros={
            "de": (agora - timedelta(days=1)).isoformat(),
            "ate": (agora + timedelta(days=1)).isoformat(),
        },
        escopo=escopo,
    )
    geracao = _geracao(sessoes, engine, armazenamento, assinador)

    await gerar_relatorio(inventario.id, geracao=geracao, ator=ator)
    await gerar_relatorio(trilha.id, geracao=geracao, ator=ator)

    planilha = load_workbook(BytesIO(armazenamento.enviados[0]["conteudo"]), read_only=True)
    nomes = [linha[1] for linha in planilha.active.iter_rows(min_row=2, values_only=True)]
    assert nomes == ["CAPS C"]
    linhas_da_trilha = armazenamento.enviados[1]["conteudo"].decode("utf-8-sig").splitlines()
    assert len(linhas_da_trilha) == 2  # cabeçalho e a criação da CAPS C
    assert "unidade.criada" in linhas_da_trilha[1]
    for pedido in (inventario, trilha):
        assert (await _obter(sessoes, pedido.id)).status is StatusDoPedido.CONCLUIDO


async def test_falha_no_envio_vira_falhou_generico_e_novo_pedido_conclui(
    sessoes: Sessoes,
    engine: AsyncEngine,
    armazenamento: ArmazenamentoFalso,
    assinador: Es256AssinadorDeRelatorio,
    rede: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """005/R2.6 (mensagem genérica, auditoria `failure`, detalhe fora do pedido e do log; nova
    tentativa é um pedido novo)"""
    pedido, ator = await _pedido(sessoes)
    armazenamento.falhar_no_envio = True

    await gerar_relatorio(
        pedido.id, geracao=_geracao(sessoes, engine, armazenamento, assinador), ator=ator
    )

    falhou = await _obter(sessoes, pedido.id)
    assert (falhou.status, falhou.erro) == (StatusDoPedido.FALHOU, ERRO_GERAL)
    assert falhou.sha256 is None
    assert falhou.assinatura is None
    [evento] = await _auditoria(sessoes, pedido.id)
    assert (evento["result"], evento["metadata"]) == ("failure", {"erro": ERRO_GERAL})
    assert "segredo" not in caplog.text
    assert "X-Amz" not in caplog.text

    armazenamento.falhar_no_envio = False
    novo, _ = await _pedido(sessoes)
    await gerar_relatorio(
        novo.id, geracao=_geracao(sessoes, engine, armazenamento, assinador), ator=ator
    )
    assert (await _obter(sessoes, novo.id)).status is StatusDoPedido.CONCLUIDO


@pytest.mark.parametrize(
    ("sse", "checksum"),
    [
        pytest.param(None, None, id="sem-sse"),
        pytest.param("aws:kms", None, id="outra-sse"),
        pytest.param("AES256", "AAAA", id="checksum-diferente"),
    ],
)
async def test_gravacao_que_nao_confere_remove_a_versao_e_falha(
    sessoes: Sessoes,
    engine: AsyncEngine,
    armazenamento: ArmazenamentoFalso,
    assinador: Es256AssinadorDeRelatorio,
    rede: dict[str, Any],
    sse: str | None,
    checksum: str | None,
) -> None:
    """005/R2.8 (a resposta do armazenamento é conferida; a versão gravada é removida)"""
    pedido, ator = await _pedido(sessoes)
    armazenamento.sse, armazenamento.checksum = sse, checksum

    await gerar_relatorio(
        pedido.id, geracao=_geracao(sessoes, engine, armazenamento, assinador), ator=ator
    )

    [enviado] = armazenamento.enviados
    assert armazenamento.removidos == [(enviado["key"], "v-1", str(pedido.solicitado_por))]
    falhou = await _obter(sessoes, pedido.id)
    assert (falhou.status, falhou.erro) == (StatusDoPedido.FALHOU, ERRO_GERAL)


async def test_relatorio_grande_demais_falha_com_a_mensagem_propria(
    sessoes: Sessoes,
    engine: AsyncEngine,
    armazenamento: ArmazenamentoFalso,
    assinador: Es256AssinadorDeRelatorio,
    rede: dict[str, Any],
) -> None:
    """005/R2.6 (limite de linhas, design § Geração e envio, passo 2)"""
    pedido, ator = await _pedido(sessoes)

    def gerador_pequeno(
        formato: str, destino: BinaryIO, colunas: tuple[Coluna, ...]
    ) -> GeradorDeArquivo:
        return novo_gerador(formato, destino, colunas, limite=1)

    geracao = _geracao(sessoes, engine, armazenamento, assinador, novo_gerador=gerador_pequeno)
    await gerar_relatorio(pedido.id, geracao=geracao, ator=ator)

    falhou = await _obter(sessoes, pedido.id)
    assert (falhou.status, falhou.erro) == (StatusDoPedido.FALHOU, MENSAGEM_GRANDE_DEMAIS)
    assert armazenamento.enviados == []


async def test_so_gera_pedido_pendente(
    sessoes: Sessoes,
    engine: AsyncEngine,
    armazenamento: ArmazenamentoFalso,
    assinador: Es256AssinadorDeRelatorio,
    rede: dict[str, Any],
) -> None:
    """005/R1.1 (passo 1: `gerando` só se `pendente`; a segunda chamada não faz nada)"""
    pedido, ator = await _pedido(sessoes)
    geracao = _geracao(sessoes, engine, armazenamento, assinador)

    await gerar_relatorio(pedido.id, geracao=geracao, ator=ator)
    await gerar_relatorio(pedido.id, geracao=geracao, ator=ator)

    assert len(armazenamento.enviados) == 1
    assert len(await _auditoria(sessoes, pedido.id)) == 1


async def test_escopo_gravado_fora_do_formato_falha_fechado(
    sessoes: Sessoes,
    engine: AsyncEngine,
    armazenamento: ArmazenamentoFalso,
    assinador: Es256AssinadorDeRelatorio,
    rede: dict[str, Any],
) -> None:
    """005/R1.3 (nada é gerado com um escopo que não se lê)"""
    pedido, ator = await _pedido(sessoes)
    async with sessoes() as sessao, sessao.begin():
        await sessao.execute(
            text("UPDATE report_jobs SET scope_snapshot = :escopo WHERE id = :id"),
            {"escopo": json.dumps({"global": "sim"}), "id": pedido.id},
        )

    await gerar_relatorio(
        pedido.id, geracao=_geracao(sessoes, engine, armazenamento, assinador), ator=ator
    )

    assert (await _obter(sessoes, pedido.id)).status is StatusDoPedido.FALHOU
    assert armazenamento.enviados == []


async def test_interrompidos_viram_falhou_na_subida(sessoes: Sessoes) -> None:
    """005/R2.6 (passo 8: `pendente` e `gerando` viram `falhou` com "Interrompido")"""
    pendente, _ = await _pedido(sessoes)
    gerando, _ = await _pedido(sessoes)
    async with sessoes() as sessao, sessao.begin():
        await SqlRepositorioDePedidos(sessao).marcar_gerando(gerando.id, datetime.now(UTC))

    marcados = await marcar_interrompidos(
        transacoes=_transacoes(sessoes), agora=lambda: datetime.now(UTC)
    )

    assert marcados == 2
    for pedido in (pendente, gerando):
        falhou = await _obter(sessoes, pedido.id)
        assert (falhou.status, falhou.erro) == (StatusDoPedido.FALHOU, ERRO_INTERROMPIDO)
        [evento] = await _auditoria(sessoes, pedido.id)
        assert (evento["actor_type"], evento["result"]) == ("sistema", "failure")
