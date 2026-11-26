"""Rotas dos relatórios sobre o PostgreSQL, com o S3 trocado por um falso (005/T6).

Design da 005 § Rotas, § Escopo dos relatórios e § Fluxo (Pedido e Download). A geração em
segundo plano roda dentro da chamada do `httpx.ASGITransport`: depois do `POST`, o pedido já
terminou.
"""

from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import text

from src.core.ids import uuid7
from src.main import create_app
from src.modules.reports.application.gerar import Geracao
from tests.factories import make_jwt_private_keys, make_settings
from tests.integration.acesso import GLOBAL, Sessoes, bearer, id_pelo_codigo, logado
from tests.integration.postgres import BancoDeTeste
from tests.integration.reports.falsos import URL_ASSINADA, ArmazenamentoFalso

RELATORIOS = "/api/v1/relatorios"
INVENTARIO = {"tipo": "inventario_unidades", "formato": "csv"}


def _trilha(dias: int = 30) -> dict[str, Any]:
    agora = datetime.now(UTC)
    return {
        "tipo": "trilha_auditoria",
        "formato": "xlsx",
        "filtros": {
            "de": (agora - timedelta(days=dias)).isoformat(),
            "ate": (agora + timedelta(minutes=1)).isoformat(),
        },
    }


@pytest.fixture
def armazenamento() -> ArmazenamentoFalso:
    return ArmazenamentoFalso()


@pytest.fixture
async def app(banco: BancoDeTeste, armazenamento: ArmazenamentoFalso) -> AsyncIterator[FastAPI]:
    """O app de produção com o S3 ligado, mas com o armazenamento falso."""
    aplicacao = create_app(
        make_settings(
            database_url=SecretStr(banco.url_api),
            s3_bucket="sgs-relatorios",
            s3_region="us-east-1",
            s3_access_key_id=SecretStr("sgs-lab-exemplo"),
            s3_secret_access_key=SecretStr("sgs-lab-exemplo-s3"),
            report_signing_keys=make_jwt_private_keys("rel-2026-11-26"),
        )
    )
    geracao: Geracao = aplicacao.state.geracao_de_relatorios
    aplicacao.state.geracao_de_relatorios = replace(geracao, armazenamento=armazenamento)
    yield aplicacao
    await aplicacao.state.engine.dispose()


async def _quem(app: FastAPI, sessoes: Sessoes, papel: str, escopo: Any = GLOBAL) -> dict[str, str]:
    return bearer(app, await logado(sessoes, (papel, escopo)))


async def _area(sessoes: Sessoes, codigo: str = "SAUDE_MENTAL") -> tuple[str, str]:
    return ("area", str(await id_pelo_codigo(sessoes, "area", codigo)))


async def _pedir(cliente: httpx.AsyncClient, cabecalho: dict[str, str], corpo: Any) -> str:
    resposta = await cliente.post(RELATORIOS, json=corpo, headers=cabecalho)
    assert resposta.status_code == 202, resposta.text
    assert resposta.json()["status"] == "pendente"
    return str(resposta.json()["id"])


async def _status(cliente: httpx.AsyncClient, url: str, cabecalho: dict[str, str]) -> int:
    return (await cliente.get(url, headers=cabecalho)).status_code


async def _auditoria(sessoes: Sessoes, acao: str, pedido: str) -> list[dict[str, Any]]:
    async with sessoes() as sessao:
        resultado = await sessao.execute(
            text(
                "SELECT actor_user_id, result, metadata FROM audit_log"
                " WHERE action = :acao AND entity_id = :id ORDER BY id"
            ),
            {"acao": acao, "id": pedido},
        )
        return [dict(linha) for linha in resultado.mappings()]


async def test_sem_token_responde_401(cliente: httpx.AsyncClient) -> None:
    """005/R1.1, R3.1 (401 sem access token)"""
    respostas = [
        await cliente.post(RELATORIOS, json=INVENTARIO),
        await cliente.get(RELATORIOS),
        await cliente.get(f"{RELATORIOS}/{uuid7()}"),
        await cliente.get(f"{RELATORIOS}/{uuid7()}/download"),
    ]

    assert [r.status_code for r in respostas] == [401] * 4


async def test_sem_relatorio_export_responde_403(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """005/R1.1 (`TECNICO_DISTRITAL` não tem `relatorio:export`)"""
    tecnico = await _quem(app, sessoes, "TECNICO_DISTRITAL")

    assert (await cliente.post(RELATORIOS, json=INVENTARIO, headers=tecnico)).status_code == 403
    assert (await cliente.get(RELATORIOS, headers=tecnico)).status_code == 403


async def test_trilha_sem_auditoria_read_responde_403_e_audita(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """005/R1.4 (a `DIRETORIA` exporta, mas não tem `auditoria:read`)"""
    diretoria = await _quem(app, sessoes, "DIRETORIA")

    resposta = await cliente.post(RELATORIOS, json=_trilha(), headers=diretoria)

    assert resposta.status_code == 403
    async with sessoes() as sessao:
        negados = await sessao.scalar(
            text("SELECT count(*) FROM audit_log WHERE action = 'acesso.negado'")
        )
        pedidos = await sessao.scalar(text("SELECT count(*) FROM report_jobs"))
    assert negados == 1
    assert pedidos == 0
    assert (await cliente.post(RELATORIOS, json=INVENTARIO, headers=diretoria)).status_code == 202


@pytest.mark.parametrize(
    "corpo",
    [
        pytest.param(_trilha(dias=367), id="periodo-maior-que-366-dias"),
        pytest.param(
            {"tipo": "trilha_auditoria", "formato": "csv", "filtros": {}}, id="sem-periodo"
        ),
        pytest.param({"tipo": "outro", "formato": "csv"}, id="tipo"),
        pytest.param({"tipo": "inventario_unidades", "formato": "pdf"}, id="formato"),
        pytest.param({**INVENTARIO, "filtros": {"cidade": "Recife"}}, id="filtro-desconhecido"),
        pytest.param({**INVENTARIO, "filtros": {"distrito_id": "1"}}, id="id-em-texto"),
        pytest.param({**INVENTARIO, "filtros": {"distrito_id": 32000}}, id="distrito-inexistente"),
        pytest.param({**INVENTARIO, "extra": 1}, id="campo-a-mais"),
    ],
)
async def test_filtros_invalidos_respondem_422_sem_gravar(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes, corpo: dict[str, Any]
) -> None:
    """005/R1.5"""
    gestor = await _quem(app, sessoes, "GESTOR_DADOS")

    resposta = await cliente.post(RELATORIOS, json=corpo, headers=gestor)

    assert resposta.status_code == 422, resposta.text
    async with sessoes() as sessao:
        assert await sessao.scalar(text("SELECT count(*) FROM report_jobs")) == 0


async def test_distrito_inexistente_aponta_o_campo(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """005/R1.5 (ids que não existem no banco dão 422 no campo)"""
    gestor = await _quem(app, sessoes, "GESTOR_DADOS")
    corpo = {**INVENTARIO, "filtros": {"distrito_id": 32000, "tipo_unidade_id": 1}}

    resposta = await cliente.post(RELATORIOS, json=corpo, headers=gestor)

    assert [e["campo"] for e in resposta.json()["errors"]] == ["filtros.distrito_id"]


async def test_pedido_gera_e_consulta_traz_integridade(
    app: FastAPI,
    cliente: httpx.AsyncClient,
    sessoes: Sessoes,
    armazenamento: ArmazenamentoFalso,
) -> None:
    """005/R1.1, R1.3, R3.1, R5.3 (202; escopo gravado; concluído com `integridade`; auditoria
    de `relatorio.solicitado`)"""
    coord = await _quem(app, sessoes, "COORD_TECNICO", await _area(sessoes))

    pedido = await _pedir(cliente, coord, _trilha())
    resposta = await cliente.get(f"{RELATORIOS}/{pedido}", headers=coord)

    corpo = resposta.json()
    assert resposta.status_code == 200
    assert corpo["status"] == "concluido", corpo
    assert corpo["vencido"] is False
    assert corpo["erro"] is None
    assert corpo["integridade"]["algoritmo"] == "ES256"
    assert corpo["integridade"]["kid"] == "rel-2026-11-26"
    assert len(corpo["integridade"]["sha256"]) == 64
    [enviado] = armazenamento.enviados
    assert enviado["key"].endswith(f"{pedido}.xlsx")
    async with sessoes() as sessao:
        escopo = await sessao.scalar(
            text("SELECT scope_snapshot FROM report_jobs WHERE id = :id"), {"id": UUID(pedido)}
        )
    area = int((await _area(sessoes))[1])
    assert escopo == {"global": False, "areas": [area], "distritos": [], "unidades": []}
    [solicitado] = await _auditoria(sessoes, "relatorio.solicitado", pedido)
    assert solicitado["metadata"] == {"tipo": "trilha_auditoria", "formato": "xlsx"}
    assert len(await _auditoria(sessoes, "relatorio.exportado", pedido)) == 1


async def test_listagem_traz_os_proprios_ou_todos_para_o_gestor_de_dados(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """005/R3.5"""
    diretoria = await _quem(app, sessoes, "DIRETORIA")
    auditor = await _quem(app, sessoes, "AUDITOR")
    gestor = await _quem(app, sessoes, "GESTOR_DADOS")
    da_diretoria = await _pedir(cliente, diretoria, INVENTARIO)
    do_auditor = await _pedir(cliente, auditor, _trilha())

    da_diretoria_lista = (await cliente.get(RELATORIOS, headers=diretoria)).json()
    todos = (await cliente.get(RELATORIOS, headers=gestor)).json()
    concluidos = await cliente.get(RELATORIOS, params={"status": "concluido"}, headers=gestor)
    pendentes = await cliente.get(RELATORIOS, params={"status": "pendente"}, headers=gestor)

    assert [i["id"] for i in da_diretoria_lista["itens"]] == [da_diretoria]
    assert [i["id"] for i in todos["itens"]] == [do_auditor, da_diretoria]
    assert todos["total"] == 2
    assert concluidos.json()["total"] == 2
    assert pendentes.json()["total"] == 0
    assert (
        await cliente.get(RELATORIOS, params={"status": "x"}, headers=gestor)
    ).status_code == 422


async def test_consulta_por_outra_pessoa_so_com_escopo_que_cubra(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """005/R3.3 (solicitante, ou escopo que cubra o gravado na mesma permissão de dados)"""
    area = await _area(sessoes)
    coord = await _quem(app, sessoes, "COORD_TECNICO", area)
    outro_da_area = await _quem(app, sessoes, "COORD_TECNICO", area)
    de_outra_area = await _quem(app, sessoes, "COORD_TECNICO", await _area(sessoes, "SAUDE_BUCAL"))
    gestor = await _quem(app, sessoes, "GESTOR_DADOS")
    pedido = await _pedir(cliente, coord, _trilha())

    url = f"{RELATORIOS}/{pedido}"
    assert (await cliente.get(url, headers=outro_da_area)).status_code == 200
    assert (await cliente.get(url, headers=gestor)).status_code == 200
    assert (await cliente.get(url, headers=de_outra_area)).status_code == 403
    assert (await cliente.get(f"{url}/download", headers=de_outra_area)).status_code == 403
    assert await _status(cliente, f"{RELATORIOS}/{uuid7()}", gestor) == 404


async def test_download_responde_url_no_store_e_audita_sem_a_url(
    app: FastAPI,
    cliente: httpx.AsyncClient,
    sessoes: Sessoes,
    armazenamento: ArmazenamentoFalso,
) -> None:
    """005/R3.2, R3.4, R3.6, R2.1 (200 `{url, expira_em}`; `no-store`; sessão de quem baixa;
    `relatorio.baixado` sem a URL)"""
    gestor_sessao = await logado(sessoes, ("GESTOR_DADOS", GLOBAL))
    gestor = bearer(app, gestor_sessao)
    pedido = await _pedir(cliente, gestor, INVENTARIO)

    resposta = await cliente.get(f"{RELATORIOS}/{pedido}/download", headers=gestor)

    assert resposta.status_code == 200, resposta.text
    assert resposta.headers["cache-control"] == "no-store"
    assert resposta.json()["url"] == URL_ASSINADA
    assert datetime.fromisoformat(resposta.json()["expira_em"]) > datetime.now(UTC)
    [(key, nome, sessao)] = armazenamento.urls
    assert key == armazenamento.enviados[0]["key"]
    assert nome == f"sgs-inventario_unidades-{datetime.now(UTC):%Y-%m-%d}.csv"
    assert sessao == str(gestor_sessao.user_id)
    [baixado] = await _auditoria(sessoes, "relatorio.baixado", pedido)
    assert set(baixado["metadata"]) == {"expira_em"}
    async with sessoes() as sessao_db:
        trilha = await sessao_db.scalar(
            text("SELECT string_agg(metadata::text, ' ') FROM audit_log")
        )
    assert "X-Amz-Signature" not in str(trilha)


async def test_download_de_pedido_nao_concluido_ou_vencido_responde_409(
    app: FastAPI,
    cliente: httpx.AsyncClient,
    sessoes: Sessoes,
    armazenamento: ArmazenamentoFalso,
) -> None:
    """005/R3.2 (409 se não concluído ou vencido); 404 se não existe"""
    gestor = await _quem(app, sessoes, "GESTOR_DADOS")
    armazenamento.falhar_no_envio = True
    falhou = await _pedir(cliente, gestor, INVENTARIO)
    armazenamento.falhar_no_envio = False
    vencido = await _pedir(cliente, gestor, INVENTARIO)
    async with sessoes() as sessao, sessao.begin():
        await sessao.execute(
            text("UPDATE report_jobs SET expires_at = now() - interval '1 day' WHERE id = :id"),
            {"id": UUID(vencido)},
        )

    assert (await cliente.get(f"{RELATORIOS}/{falhou}", headers=gestor)).json()[
        "status"
    ] == "falhou"
    assert await _status(cliente, f"{RELATORIOS}/{falhou}/download", gestor) == 409
    consulta = (await cliente.get(f"{RELATORIOS}/{vencido}", headers=gestor)).json()
    assert consulta["vencido"] is True
    assert (
        await cliente.get(f"{RELATORIOS}/{vencido}/download", headers=gestor)
    ).status_code == 409
    assert (
        await cliente.get(f"{RELATORIOS}/{uuid7()}/download", headers=gestor)
    ).status_code == 404
    assert armazenamento.urls == []


async def test_sem_s3_bucket_pedido_e_download_respondem_503(
    banco: BancoDeTeste, sessoes: Sessoes
) -> None:
    """005/R2.9 (exportação desligada sem `S3_BUCKET`: 503)"""
    aplicacao = create_app(make_settings(database_url=SecretStr(banco.url_api)))
    transporte = httpx.ASGITransport(app=aplicacao)
    try:
        async with httpx.AsyncClient(transport=transporte, base_url="https://teste") as cliente:
            gestor = bearer(aplicacao, await logado(sessoes, ("GESTOR_DADOS", GLOBAL)))
            pedido = await cliente.post(RELATORIOS, json=INVENTARIO, headers=gestor)
            download = await cliente.get(f"{RELATORIOS}/{uuid7()}/download", headers=gestor)
            lista = await cliente.get(RELATORIOS, headers=gestor)
    finally:
        await aplicacao.state.engine.dispose()

    assert (pedido.status_code, download.status_code, lista.status_code) == (503, 503, 200)
