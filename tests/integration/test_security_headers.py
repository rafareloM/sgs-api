"""Cabeçalhos de segurança, CORS e documentação OpenAPI por ambiente (spec 001, R6)."""

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr

from src.core.config import AppEnv, DatabaseSslMode
from src.main import create_app
from tests.factories import URL_SEM_BANCO, make_settings

ORIGEM_DO_FRONT = "https://app.sgs.localhost"

CABECALHOS_DE_SEGURANCA = {
    "strict-transport-security": "max-age=63072000; includeSubDomains",
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "cache-control": "no-store",
}


def _cliente(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://teste")


def _app_de_producao() -> FastAPI:
    return create_app(
        make_settings(
            app_env=AppEnv.PROD,
            database_url=SecretStr("postgresql+asyncpg://sgs_api:Kx9-segredo@db.interno:5432/sgs"),
            database_ssl_mode=DatabaseSslMode.VERIFY_FULL,
        )
    )


@pytest.mark.parametrize("caminho", ["/health/live", "/rota-que-nao-existe"])
async def test_respostas_levam_os_cabecalhos_de_seguranca(caminho: str) -> None:
    """001/R6.1"""
    async with _cliente(create_app(make_settings())) as cliente:
        resposta = await cliente.get(caminho)

    for nome, valor in CABECALHOS_DE_SEGURANCA.items():
        assert resposta.headers[nome] == valor


async def test_cors_aceita_a_origem_configurada() -> None:
    """001/R6.2"""
    app = create_app(make_settings(cors_origins=(ORIGEM_DO_FRONT,)))
    async with _cliente(app) as cliente:
        resposta = await cliente.options(
            "/health/live",
            headers={
                "Origin": ORIGEM_DO_FRONT,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "Authorization",
            },
        )

    assert resposta.status_code == 200
    assert resposta.headers["access-control-allow-origin"] == ORIGEM_DO_FRONT
    assert resposta.headers["access-control-allow-credentials"] == "true"


@pytest.mark.parametrize("metodo", ["OPTIONS", "GET"])
async def test_cors_recusa_origem_nao_configurada(metodo: str) -> None:
    """001/R6.2"""
    app = create_app(make_settings(cors_origins=(ORIGEM_DO_FRONT,)))
    cabecalhos = {"Origin": "https://malicioso.example", "Access-Control-Request-Method": "GET"}
    async with _cliente(app) as cliente:
        resposta = await cliente.request(metodo, "/health/live", headers=cabecalhos)

    assert "access-control-allow-origin" not in resposta.headers


@pytest.mark.parametrize("app_env", [AppEnv.DEV, AppEnv.TEST])
async def test_documentacao_openapi_disponivel_em_dev_e_test(app_env: AppEnv) -> None:
    """001/R6.3"""
    settings = make_settings(app_env=app_env, database_migration_url=SecretStr(URL_SEM_BANCO))
    async with _cliente(create_app(settings)) as cliente:
        assert (await cliente.get("/openapi.json")).status_code == 200
        assert (await cliente.get("/docs")).status_code == 200


@pytest.mark.parametrize("caminho", ["/openapi.json", "/docs", "/redoc"])
async def test_documentacao_openapi_ausente_em_prod(caminho: str) -> None:
    """001/R6.3"""
    async with _cliente(_app_de_producao()) as cliente:
        resposta = await cliente.get(caminho)

    assert resposta.status_code == 404
