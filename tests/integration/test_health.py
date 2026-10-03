"""Saúde do processo, identificador de requisição e log de acesso (spec 001, R1.3 e R4)."""

import json
import re
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from sgs_api.main import create_app
from tests.factories import make_settings

UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _cliente(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://teste")


def _linhas_de_log(saida: str) -> list[dict[str, Any]]:
    return [json.loads(linha) for linha in saida.splitlines() if linha.strip()]


async def test_health_live_responde_200() -> None:
    """001/R1.3"""
    async with _cliente(create_app(make_settings())) as cliente:
        resposta = await cliente.get("/health/live")

    assert resposta.status_code == 200
    assert resposta.json() == {"status": "ok"}


async def test_gera_request_id_quando_a_requisicao_nao_traz() -> None:
    """001/R4.2"""
    async with _cliente(create_app(make_settings())) as cliente:
        resposta = await cliente.get("/health/live")

    assert UUID.fullmatch(resposta.headers["X-Request-ID"])


async def test_devolve_o_request_id_recebido() -> None:
    """001/R4.2"""
    async with _cliente(create_app(make_settings())) as cliente:
        resposta = await cliente.get("/health/live", headers={"X-Request-ID": "front-42.abc_1"})

    assert resposta.headers["X-Request-ID"] == "front-42.abc_1"


@pytest.mark.parametrize("recebido", ["a" * 129, "com espaco", "quebra\tde-linha", "<script>"])
async def test_troca_request_id_recebido_fora_do_formato(recebido: str) -> None:
    """001/R4.2 (formato restrito evita injeção nos logs)"""
    async with _cliente(create_app(make_settings())) as cliente:
        resposta = await cliente.get("/health/live", headers={"X-Request-ID": recebido})

    assert UUID.fullmatch(resposta.headers["X-Request-ID"])


async def test_registra_cada_requisicao_em_log_json(capsys: pytest.CaptureFixture[str]) -> None:
    """001/R4.1"""
    app = create_app(make_settings())
    async with _cliente(app) as cliente:
        await cliente.get("/health/live", headers={"X-Request-ID": "req-1"})
        await cliente.get("/rota-que-nao-existe", headers={"X-Request-ID": "req-2"})

    linhas = [linha for linha in _linhas_de_log(capsys.readouterr().out) if "status" in linha]
    assert [linha["request_id"] for linha in linhas] == ["req-1", "req-2"]
    primeira = linhas[0]
    assert primeira["method"] == "GET"
    assert primeira["route"] == "/health/live"
    assert primeira["status"] == 200
    assert isinstance(primeira["duration_ms"], float)
    assert linhas[1]["status"] == 404


async def test_log_de_acesso_nao_registra_query_cabecalhos_nem_cookies(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """001/R4.3"""
    app = create_app(make_settings())
    cabecalhos = {"Authorization": "Bearer segredo-no-cabecalho", "Cookie": "sid=segredo-cookie"}
    async with _cliente(app) as cliente:
        await cliente.get("/health/live?token=segredo-na-query", headers=cabecalhos)

    saida = capsys.readouterr().out
    assert _linhas_de_log(saida)
    assert "segredo" not in saida
