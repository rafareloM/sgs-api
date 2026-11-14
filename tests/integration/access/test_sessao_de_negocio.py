"""`SessaoDeNegocio`: uma sessão e uma transação de negócio por requisição (padrão da 006/T3).

Rotas de teste; as de verdade (006, 011) seguem o mesmo padrão. A criação de unidade
(`tests/integration/registry/test_criar_unidade.py`) cobre a confirmação e o `AcessoNegado`
levantado pelo caso de uso.
"""

from collections.abc import AsyncIterator
from typing import Annotated

import httpx
import pytest
from fastapi import APIRouter, Depends, FastAPI, Request
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.core.errors import Conflict
from src.main import create_app
from src.modules.access.api.deps import (
    SessaoDeNegocio,
    UsuarioAtual,
    ator_da_requisicao,
    require,
)
from src.modules.audit.application.registrar import registrar
from tests.factories import make_settings
from tests.integration.acesso import GLOBAL, Sessoes, bearer, eventos, logado
from tests.integration.postgres import BancoDeTeste, motor


def _rotas_de_teste() -> APIRouter:
    rotas = APIRouter(prefix="/api/v1/teste/sessao")

    @rotas.post("/grava-e-falha")
    async def grava_e_falha(
        request: Request,
        usuario: Annotated[UsuarioAtual, Depends(require("auditoria:read"))],
        sessao: SessaoDeNegocio,
    ) -> None:
        await registrar(
            request.app.state.auditoria(sessao),
            acao="teste.gravado",
            ator=ator_da_requisicao(request, usuario),
        )
        raise Conflict("Falhou depois de gravar.")

    # A sessão declarada antes do `require`: o 403 dele passa pela dependência da sessão.
    @rotas.get("/sessao-antes-do-require")
    async def sessao_antes(
        sessao: SessaoDeNegocio,
        usuario: Annotated[UsuarioAtual, Depends(require("auditoria:read"))],
    ) -> None:
        return None

    return rotas


@pytest.fixture
async def app(banco: BancoDeTeste) -> AsyncIterator[FastAPI]:
    app = create_app(make_settings(database_url=SecretStr(banco.url_api)))
    app.include_router(_rotas_de_teste())
    yield app
    await app.state.engine.dispose()


@pytest.fixture
async def cliente(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transporte = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transporte, base_url="http://teste") as cliente:
        yield cliente


@pytest.fixture
async def sessoes(banco: BancoDeTeste) -> AsyncIterator[Sessoes]:
    engine = motor(banco.url_api)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def test_erro_no_handler_desfaz_o_que_foi_gravado_inclusive_a_auditoria(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """AGENTS.md, regra 5 (001/R5.1): negócio e auditoria na mesma transação, desfeitos juntos."""
    auditor = await logado(sessoes, ("AUDITOR", GLOBAL))

    resposta = await cliente.post(
        "/api/v1/teste/sessao/grava-e-falha", headers=bearer(app, auditor)
    )

    assert resposta.status_code == 409
    assert await eventos(sessoes, "teste.gravado") == []


async def test_negacao_do_require_e_auditada_uma_vez_seja_qual_for_a_ordem(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """003/R4.6: `acesso.negado` uma vez só, mesmo com a sessão declarada antes do `require`."""
    diretoria = await logado(sessoes, ("DIRETORIA", GLOBAL))

    resposta = await cliente.get(
        "/api/v1/teste/sessao/sessao-antes-do-require", headers=bearer(app, diretoria)
    )

    assert resposta.status_code == 403
    assert len(await eventos(sessoes, "acesso.negado")) == 1
