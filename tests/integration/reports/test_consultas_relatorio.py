"""Consultas dos relatórios em SQL explícito sobre o PostgreSQL (005/T11).

Os dados entram pela API: três unidades em dois distritos, uma com o nome do gestor (dado
pessoal, que a trilha grava como `***`). Os eventos de acesso, de auditoria e os de ação com `_`
entram direto pelo caso de uso da auditoria, como entrariam pelas rotas.
"""

from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI

from src.modules.audit.application.registrar import Ator, Entidade, Mudanca, registrar
from src.modules.audit.infrastructure.repository import SqlAuditStore
from src.modules.reports.domain.colunas import COLUNAS_POR_TIPO
from src.modules.reports.domain.escopo import EscopoGravado
from src.modules.reports.domain.filtros import Filtros, FiltrosDaTrilha, FiltrosDoInventario
from src.modules.reports.infrastructure.consultas import SqlConsultasDeRelatorio
from tests.integration.acesso import GLOBAL, Sessoes, bearer, id_pelo_codigo, logado
from tests.integration.postgres import BancoDeTeste, motor

GLOBAL_ = EscopoGravado(global_=True)
NOME_DO_GESTOR = "Fulana de Tal"


@pytest.fixture
async def consultas(banco: BancoDeTeste) -> AsyncIterator[SqlConsultasDeRelatorio]:
    """Com o login da API (papel sgs_app), como em produção."""
    engine = motor(banco.url_api)
    yield SqlConsultasDeRelatorio(engine)
    await engine.dispose()


@pytest.fixture
async def rede(app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes) -> dict[str, Any]:
    gestor = bearer(app, await logado(sessoes, ("GESTOR_DADOS", GLOBAL)))
    ds1 = await id_pelo_codigo(sessoes, "distrito", "DS-I")
    ds2 = await id_pelo_codigo(sessoes, "distrito", "DS-II")
    caps = await id_pelo_codigo(sessoes, "tipo_unidade", "CAPS_II")

    async def unidade(nome: str, distrito: int, cnes: str, **extra: Any) -> str:
        corpo = {
            "nome": nome,
            "tipo_unidade_id": caps,
            "distrito_id": distrito,
            "cep": "50010100",
            "endereco": "Rua A, 1",
            "status": "ativa",
            "cnes": cnes,
            **extra,
        }
        resposta = await cliente.post("/api/v1/unidades", json=corpo, headers=gestor)
        assert resposta.status_code == 201, resposta.text
        return str(resposta.json()["id"])

    a = await unidade("CAPS A", ds1, "0111111")
    b = await unidade("=CAPS B", ds1, "2222222")
    c = await unidade("CAPS C", ds2, "3333333", nome_gestor=NOME_DO_GESTOR)

    async with sessoes() as sessao, sessao.begin():
        store = SqlAuditStore(sessao)
        sistema = Ator(tipo="sistema", origem="teste")
        for acao, entidade in (
            ("auth.login", None),
            ("acesso.negado", Entidade("unidade", c)),
            ("acesso.exportado", None),
            ("auditoria.verificada", None),
            ("papel_x.atribuido", Entidade("papel", "1")),
            ("papelzx.atribuido", Entidade("papel", "2")),
        ):
            await registrar(store, acao=acao, ator=sistema, entidade=entidade)
        await registrar(
            store,
            acao="papel.alterado",
            ator=sistema,
            entidade=Entidade("papel", "3"),
            mudancas=[Mudanca("nome", "Antigo", "Novo"), Mudanca("ativo", True, None)],
        )
    return {"a": a, "b": b, "c": c, "ds1": ds1, "ds2": ds2}


async def _linhas(
    consultas: SqlConsultasDeRelatorio,
    tipo: str,
    filtros: Filtros,
    escopo: EscopoGravado,
    tamanho: int = 1_000,
) -> list[Sequence[object]]:
    linhas: list[Sequence[object]] = []
    async for lote in consultas.lotes(tipo, filtros, escopo, tamanho=tamanho):
        assert 0 < len(lote) <= tamanho
        linhas.extend(lote)
    for linha in linhas:
        assert len(linha) == len(COLUNAS_POR_TIPO[tipo])
    return linhas


def _periodo(**extra: Any) -> FiltrosDaTrilha:
    agora = datetime.now(UTC)
    return FiltrosDaTrilha(de=agora - timedelta(days=1), ate=agora + timedelta(days=1), **extra)


async def test_inventario_no_escopo_gravado_com_filtros_e_em_lotes(
    consultas: SqlConsultasDeRelatorio, rede: dict[str, Any]
) -> None:
    """005/R1.3 (só o escopo gravado; ids de escopo fora do arquivo; lotes do cursor)"""
    todas = await _linhas(consultas, "inventario_unidades", FiltrosDoInventario(), GLOBAL_, 2)
    do_ds2 = await _linhas(
        consultas,
        "inventario_unidades",
        FiltrosDoInventario(),
        EscopoGravado(distritos=(rede["ds2"],)),
    )
    filtrado = await _linhas(
        consultas, "inventario_unidades", FiltrosDoInventario(distrito_id=rede["ds1"]), GLOBAL_
    )
    inativas = await _linhas(
        consultas, "inventario_unidades", FiltrosDoInventario(status="inativa"), GLOBAL_
    )
    so_a = await _linhas(
        consultas,
        "inventario_unidades",
        FiltrosDoInventario(),
        EscopoGravado(unidades=(UUID(rede["a"]),)),
    )

    assert sorted(str(linha[0]) for linha in todas) == ["0111111", "2222222", "3333333"]
    assert [linha[1] for linha in do_ds2] == ["CAPS C"]
    assert sorted(str(linha[1]) for linha in filtrado) == ["=CAPS B", "CAPS A"]
    assert inativas == []
    assert [linha[1] for linha in so_a] == ["CAPS A"]
    assert all(rede[u] not in map(str, linha) for linha in todas for u in ("a", "b", "c"))
    assert all(NOME_DO_GESTOR not in map(str, linha) for linha in todas)


async def test_escopo_vazio_nao_traz_linha(
    consultas: SqlConsultasDeRelatorio, rede: dict[str, Any]
) -> None:
    """005/R1.3 (deny by default)"""
    vazio = EscopoGravado()

    assert await _linhas(consultas, "inventario_unidades", FiltrosDoInventario(), vazio) == []
    assert await _linhas(consultas, "trilha_auditoria", _periodo(), vazio) == []


async def test_trilha_global_sem_eventos_de_acesso_e_sem_dado_pessoal(
    consultas: SqlConsultasDeRelatorio, rede: dict[str, Any]
) -> None:
    """005/R4.3 (sem `auth.*`, `acesso.*`, `auditoria.*`; nome do gestor como `***`)"""
    linhas = await _linhas(consultas, "trilha_auditoria", _periodo(), GLOBAL_)
    acoes = [str(linha[1]) for linha in linhas]

    assert not [a for a in acoes if a.startswith(("auth.", "acesso.", "auditoria."))]
    assert {"unidade.criada", "papel_x.atribuido", "papel.alterado"} <= set(acoes)
    assert all(NOME_DO_GESTOR not in map(str, linha) for linha in linhas)
    criada_c = next(linha for linha in linhas if linha[6] == rede["c"])
    assert "manager_name: — → ***" in str(criada_c[8])
    alterado = next(linha for linha in linhas if linha[1] == "papel.alterado")
    assert alterado[8] == "nome: Antigo → Novo; ativo: true → —"
    assert (alterado[2], alterado[5], alterado[6]) == ("sistema", "papel", "3")
    instantes = [linha[0] for linha in linhas if isinstance(linha[0], datetime)]
    assert len(instantes) == len(linhas)
    assert instantes == sorted(instantes)


async def test_trilha_restrita_so_traz_as_unidades_do_escopo(
    consultas: SqlConsultasDeRelatorio, rede: dict[str, Any]
) -> None:
    """005/R1.3, R4.3 (trilha pela `vw_unit_history`; sem o `acesso.negado` da unidade)"""
    linhas = await _linhas(
        consultas, "trilha_auditoria", _periodo(), EscopoGravado(distritos=(rede["ds2"],))
    )

    assert {(linha[1], linha[5], linha[6]) for linha in linhas} == {
        ("unidade.criada", "unidade", rede["c"])
    }
    assert "***" in str(linhas[0][8])
    assert "GESTOR_DADOS" in str(linhas[0][4])
    assert (
        await _linhas(
            consultas,
            "trilha_auditoria",
            _periodo(entidade_tipo="papel"),
            EscopoGravado(distritos=(rede["ds2"],)),
        )
        == []
    )


async def test_prefixo_da_acao_com_sublinhado_nao_e_curinga(
    consultas: SqlConsultasDeRelatorio, rede: dict[str, Any]
) -> None:
    """005/R1.5 (prefixo `papel_x` não pega `papelzx`, como pegaria um LIKE sem escape)"""
    linhas = await _linhas(consultas, "trilha_auditoria", _periodo(acao="papel_x"), GLOBAL_)

    assert [linha[1] for linha in linhas] == ["papel_x.atribuido"]


async def test_trilha_respeita_o_periodo_e_o_tipo_de_entidade(
    consultas: SqlConsultasDeRelatorio, rede: dict[str, Any]
) -> None:
    """005/R1.5 (`de` incluído, `ate` excluído; `entidade_tipo`)"""
    agora = datetime.now(UTC)
    passado = FiltrosDaTrilha(de=agora - timedelta(days=10), ate=agora - timedelta(days=5))
    papeis = await _linhas(consultas, "trilha_auditoria", _periodo(entidade_tipo="papel"), GLOBAL_)

    assert await _linhas(consultas, "trilha_auditoria", passado, GLOBAL_) == []
    assert {linha[5] for linha in papeis} == {"papel"}
    assert len(papeis) == 3


async def test_filtros_de_outro_tipo_sao_recusados(consultas: SqlConsultasDeRelatorio) -> None:
    """005/R1.2"""
    with pytest.raises(ValueError, match="não servem"):
        await _linhas(consultas, "trilha_auditoria", FiltrosDoInventario(), GLOBAL_)
