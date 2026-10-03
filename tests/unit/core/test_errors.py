"""Erros padronizados em application/problem+json (spec 001, R3)."""

import json
from typing import Literal

import httpx
import pytest
from fastapi import APIRouter, FastAPI
from pydantic import BaseModel, Field

from src.core.errors import (
    AppError,
    Conflict,
    DomainValidationError,
    FieldError,
    Forbidden,
    NotFound,
)
from src.main import create_app
from tests.factories import make_settings

PROBLEM_JSON = "application/problem+json"


class Entrada(BaseModel):
    nome: str = Field(min_length=3, max_length=10)
    idade: int = Field(ge=0)
    tipo: Literal["caps", "usf"]
    cep: str = Field(pattern=r"^\d{8}$")
    senha: str = Field(max_length=8)


def _app() -> FastAPI:
    app = create_app(make_settings())
    rotas = APIRouter(prefix="/teste")

    @rotas.post("/validacao")
    async def validacao(entrada: Entrada) -> dict[str, str]:
        return {"nome": entrada.nome}

    @rotas.get("/negocio/{tipo}")
    async def negocio(tipo: str) -> None:
        erros: dict[str, AppError] = {
            "nao-encontrado": NotFound("Unidade 42 não encontrada."),
            "proibido": Forbidden("Fora do seu escopo."),
            "conflito": Conflict("CNES já cadastrado."),
            "dominio": DomainValidationError(
                "A unidade tem dados inválidos.",
                errors=[FieldError(campo="cep", mensagem="CEP deve ter 8 dígitos.")],
            ),
        }
        raise erros[tipo]

    @rotas.get("/inesperado")
    async def inesperado() -> None:
        raise RuntimeError("falha em /srv/app/repo.py ao rodar SELECT senha FROM users")

    app.include_router(rotas)
    return app


def _cliente(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://teste")


def _assert_problem(resposta: httpx.Response, status: int) -> dict[str, object]:
    assert resposta.status_code == status
    assert resposta.headers["content-type"] == PROBLEM_JSON
    corpo: dict[str, object] = resposta.json()
    assert {"type", "title", "status", "detail", "request_id"} <= corpo.keys()
    assert corpo["status"] == status
    assert corpo["request_id"] == resposta.headers["X-Request-ID"]
    return corpo


@pytest.mark.parametrize(
    ("tipo", "status", "detalhe"),
    [
        ("nao-encontrado", 404, "Unidade 42 não encontrada."),
        ("proibido", 403, "Fora do seu escopo."),
        ("conflito", 409, "CNES já cadastrado."),
    ],
)
async def test_erro_de_negocio_vira_problem_json(tipo: str, status: int, detalhe: str) -> None:
    """001/R3.1"""
    async with _cliente(_app()) as cliente:
        resposta = await cliente.get(f"/teste/negocio/{tipo}")

    corpo = _assert_problem(resposta, status)
    assert corpo["detail"] == detalhe
    assert str(corpo["type"]).startswith("urn:sgs:problema:")


async def test_rota_inexistente_vira_problem_json() -> None:
    """001/R3.1"""
    async with _cliente(_app()) as cliente:
        resposta = await cliente.get("/nao-existe")

    corpo = _assert_problem(resposta, 404)
    assert corpo["title"] == "Recurso não encontrado"


async def test_metodo_nao_permitido_vira_problem_json() -> None:
    """001/R3.1"""
    async with _cliente(_app()) as cliente:
        resposta = await cliente.delete("/health/live")

    _assert_problem(resposta, 405)
    assert "GET" in resposta.headers["allow"]


async def test_validacao_responde_422_com_campo_e_mensagem_em_portugues() -> None:
    """001/R3.2"""
    async with _cliente(_app()) as cliente:
        resposta = await cliente.post(
            "/teste/validacao", json={"nome": "ab", "idade": -1, "tipo": "upa", "senha": "x"}
        )

    corpo = _assert_problem(resposta, 422)
    assert corpo["errors"] == [
        {"campo": "nome", "mensagem": "Deve ter pelo menos 3 caractere(s)."},
        {"campo": "idade", "mensagem": "Deve ser maior ou igual a 0."},
        {"campo": "tipo", "mensagem": "Valor inválido. Use um destes: 'caps' ou 'usf'."},
        {"campo": "cep", "mensagem": "Campo obrigatório."},
    ]


async def test_validacao_nao_ecoa_o_valor_enviado() -> None:
    """001/R3.2"""
    senha = "senha-longa-demais-e-secreta"
    async with _cliente(_app()) as cliente:
        resposta = await cliente.post(
            "/teste/validacao",
            json={"nome": "abc", "idade": 1, "tipo": "caps", "cep": "5000000x", "senha": senha},
        )

    corpo = _assert_problem(resposta, 422)
    assert corpo["errors"] == [
        {"campo": "cep", "mensagem": "Formato inválido."},
        {"campo": "senha", "mensagem": "Deve ter no máximo 8 caractere(s)."},
    ]
    assert senha not in resposta.text
    assert "5000000x" not in resposta.text


async def test_json_malformado_responde_422() -> None:
    """001/R3.2"""
    async with _cliente(_app()) as cliente:
        resposta = await cliente.post(
            "/teste/validacao", content=b'{"nome": ', headers={"content-type": "application/json"}
        )

    corpo = _assert_problem(resposta, 422)
    assert corpo["errors"] == [{"campo": "corpo", "mensagem": "JSON inválido."}]


async def test_erro_de_validacao_do_dominio_responde_422_com_campos() -> None:
    """001/R3.2"""
    async with _cliente(_app()) as cliente:
        resposta = await cliente.get("/teste/negocio/dominio")

    corpo = _assert_problem(resposta, 422)
    assert corpo["detail"] == "A unidade tem dados inválidos."
    assert corpo["errors"] == [{"campo": "cep", "mensagem": "CEP deve ter 8 dígitos."}]


async def test_erro_inesperado_responde_500_sem_detalhes_internos(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """001/R3.3"""
    async with _cliente(_app()) as cliente:
        resposta = await cliente.get("/teste/inesperado", headers={"X-Request-ID": "req-500"})

    corpo = _assert_problem(resposta, 500)
    for vazamento in ("RuntimeError", "Traceback", "/srv/app", "SELECT", "senha"):
        assert vazamento not in resposta.text
    assert corpo["request_id"] == "req-500"

    linhas = [json.loads(linha) for linha in capsys.readouterr().out.splitlines() if linha]
    erro = next(linha for linha in linhas if "exception" in linha)
    assert erro["request_id"] == "req-500"
    assert "RuntimeError" in erro["exception"]
    acesso = next(linha for linha in linhas if linha.get("event") == "requisicao")
    assert acesso["status"] == 500
