"""Desempenho da busca de unidades com o volume do cadastro de Recife (006/T10, 006/R2.7).

Semeia 1.000 unidades (nomes, CNES, tipos e distritos variados) num banco de teste migrado,
roda `ANALYZE` e faz uma bateria de requisições a `GET /api/v1/unidades`, misturando texto livre
(nome com e sem acento, CNES), filtros, ordenações e páginas. Mede o tempo de cada requisição do
lado do cliente e confere o p95 contra o limite de 3 s (RNF-01, design da 006 § Estratégia de
testes).

Como mede: a API roda no mesmo processo (httpx `ASGITransport`, sem rede até a API) e o banco é o
`postgres:17` do testcontainers, na mesma máquina; o tempo inclui autenticação, permissão,
escopo, a consulta `search_health_units.sql` e a serialização da resposta. O limite de 3 s é
folgado para essa medida; numa máquina de desenvolvimento o p95 fica na casa de dezenas de
milissegundos (medido em 13/11/2026: 200 buscas, p50 ~12 ms, p95 ~16 ms; o valor sai na
mensagem do teste quando ele falha).

Fica fora do `make check`; rodar à parte com `uv run pytest tests/e2e/test_busca_desempenho.py
-m slow` (precisa de Docker).
"""

import statistics
import time
from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.main import create_app
from tests.factories import make_settings
from tests.integration.acesso import GLOBAL, Sessoes, bearer, id_pelo_codigo, logado
from tests.integration.postgres import BancoDeTeste, motor
from tests.integration.registry.cadastro import inserir_unidade

pytestmark = pytest.mark.slow

LISTA = "/api/v1/unidades"
UNIDADES = 1_000
REQUISICOES = 200
LIMITE_P95_S = 3.0

DISTRITOS = ("DS-I", "DS-II", "DS-III", "DS-IV", "DS-V", "DS-VI", "DS-VII", "DS-VIII")
TIPOS = ("USF", "CAPS_II", "CAPS_AD", "CAPS_IJ", "CECON", "SIM", "POLICLINICA")
PREFIXOS = ("Unidade de Saúde da Família", "CAPS", "Policlínica", "Centro de Saúde", "USF")
BAIRROS = (
    "Ibura",
    "Água Fria",
    "Boa Viagem",
    "Casa Amarela",
    "Várzea",
    "Jordão",
    "Afogados",
    "Torrões",
    "Campo Grande",
    "Encruzilhada",
    "Imbiribeira",
    "Cordeiro",
    "São José",
)

# Textos de busca: trecho de nome, com e sem acento, caixa trocada, espaços repetidos, CNES
# inteiro e em trecho, e um texto sem resultado.
TEXTOS = (
    "ibura",
    "agua fria",
    "ÁGUA   FRIA",
    "varzea",
    "policlinica",
    "saude da familia",
    "sao jose 01",
    "2700500",
    "27004",
    "inexistente xyz",
)
ORDENS = ("nome", "distrito", "atualizacao", None)


async def _semear(banco: BancoDeTeste) -> None:
    engine = motor(banco.url_dono)
    async with engine.begin() as conexao:
        for n in range(UNIDADES):
            nome = f"{PREFIXOS[n % len(PREFIXOS)]} {BAIRROS[n % len(BAIRROS)]} {n:04d}"
            await inserir_unidade(
                conexao,
                nome,
                distrito=DISTRITOS[n % len(DISTRITOS)],
                tipo=TIPOS[n % len(TIPOS)],
                cnes=f"{2_700_000 + n:07d}",
            )
    async with engine.connect() as conexao:
        await conexao.execute(text("ANALYZE"))
    await engine.dispose()


@pytest.fixture
async def app(banco: BancoDeTeste) -> AsyncIterator[FastAPI]:
    await _semear(banco)
    app = create_app(make_settings(database_url=SecretStr(banco.url_api)))
    yield app
    await app.state.engine.dispose()


@pytest.fixture
async def sessoes(banco: BancoDeTeste) -> AsyncIterator[Sessoes]:
    engine = motor(banco.url_api)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def _consultas(sessoes: Sessoes) -> list[dict[str, str | int]]:
    """Bateria de parâmetros, determinística, cobrindo busca, filtros, ordem e paginação."""
    distritos = [await id_pelo_codigo(sessoes, "distrito", d) for d in DISTRITOS]
    tipos = [await id_pelo_codigo(sessoes, "tipo_unidade", t) for t in TIPOS]
    consultas: list[dict[str, str | int]] = []
    for n in range(REQUISICOES):
        params: dict[str, str | int] = {}
        if n % 4 != 3:
            params["q"] = TEXTOS[n % len(TEXTOS)]
        if n % 3 == 0:
            params["distrito"] = distritos[n % len(distritos)]
        if n % 5 == 0:
            params["tipo"] = tipos[n % len(tipos)]
        if n % 7 == 0:
            params["status"] = "ativa"
        ordem = ORDENS[n % len(ORDENS)]
        if ordem is not None:
            params["ordenar"] = ordem
        params["pagina"] = 1 + n % 3
        params["tamanho"] = 20 if n % 2 else 100
        consultas.append(params)
    return consultas


async def test_busca_responde_em_menos_de_3s_no_p95_com_1000_unidades(
    app: FastAPI, sessoes: Sessoes
) -> None:
    """006/R2.7: com 1.000 unidades, 95% das buscas respondem em menos de 3 s."""
    cabecalhos = bearer(app, await logado(sessoes, ("AUDITOR", GLOBAL)))
    consultas = await _consultas(sessoes)
    transporte = httpx.ASGITransport(app=app)
    tempos: list[float] = []
    async with httpx.AsyncClient(transport=transporte, base_url="http://teste") as cliente:
        # Sanidade do volume: a listagem sem filtro enxerga as 1.000 unidades.
        tudo = await cliente.get(LISTA, headers=cabecalhos)
        assert tudo.status_code == 200, tudo.text
        assert tudo.json()["total"] == UNIDADES

        for params in consultas:
            inicio = time.perf_counter()
            resposta = await cliente.get(LISTA, params=params, headers=cabecalhos)
            tempos.append(time.perf_counter() - inicio)
            assert resposta.status_code == 200, (params, resposta.text)

    p95 = statistics.quantiles(tempos, n=20, method="inclusive")[18]
    resumo = (
        f"{len(tempos)} buscas: p50 {statistics.median(tempos) * 1000:.1f} ms,"
        f" p95 {p95 * 1000:.1f} ms, máx {max(tempos) * 1000:.1f} ms"
    )
    assert p95 < LIMITE_P95_S, resumo
