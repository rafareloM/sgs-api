"""audit.registrar: mesma transação do caso de uso e hash encadeado (spec 001, R5.1 e R5.3)."""

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.modules.audit.application.registrar import Ator, Entidade, Mudanca, registrar
from src.modules.audit.domain.entry import GENESIS_HASH, AuditEntry
from src.modules.audit.infrastructure.repository import SqlAuditStore
from tests.integration.postgres import BancoDeTeste, motor

USUARIO = UUID("01928a3b-0000-7000-8000-000000000001")
SESSAO = UUID("01928a3b-0000-7000-8000-0000000000aa")


class FalhaSimuladaError(Exception):
    pass


@pytest.fixture
async def sessoes(banco: BancoDeTeste) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Sessões com o login da API: só INSERT e SELECT na trilha, como em produção."""
    engine = motor(banco.url_api)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def _registrar(sessoes: async_sessionmaker[AsyncSession], acao: str) -> AuditEntry:
    async with sessoes() as sessao, sessao.begin():
        return await registrar(
            SqlAuditStore(sessao),
            acao=acao,
            ator=Ator(user_id=USUARIO, ip="10.0.0.1", request_id=f"req-{acao}"),
        )


async def _trilha(sessoes: async_sessionmaker[AsyncSession]) -> list[dict[str, Any]]:
    async with sessoes() as sessao:
        resultado = await sessao.execute(text("SELECT * FROM audit_log ORDER BY id"))
        return [dict(linha) for linha in resultado.mappings()]


async def _cabeca(sessoes: async_sessionmaker[AsyncSession]) -> str:
    async with sessoes() as sessao:
        return str(await sessao.scalar(text("SELECT last_hash FROM audit_chain_head")))


def _do_banco(linha: dict[str, Any]) -> AuditEntry:
    """Reconstrói o registro a partir da linha gravada, como faria uma verificação da trilha."""
    return AuditEntry(
        occurred_at=linha["occurred_at"],
        action=linha["action"],
        actor=Ator(
            user_id=linha["actor_user_id"],
            papeis=tuple(linha["actor_roles"]),
            session_id=linha["session_id"],
            ip=linha["ip"],
            request_id=linha["request_id"],
        ),
        entity=(
            Entidade(tipo=linha["entity_type"], id=linha["entity_id"])
            if linha["entity_type"]
            else None
        ),
        changes=tuple(Mudanca(**mudanca) for mudanca in linha["changes"]),
        metadata=linha["metadata"],
        prev_hash=linha["prev_hash"],
        hash=linha["hash"],
    )


def _assert_cadeia_integra(trilha: list[dict[str, Any]], cabeca: str) -> None:
    anterior = GENESIS_HASH
    for linha in trilha:
        registro = _do_banco(linha)
        assert registro.prev_hash == anterior
        assert registro.recompute_hash() == registro.hash
        anterior = registro.hash
    assert cabeca == anterior


async def test_registra_na_transacao_do_caso_de_uso_com_todos_os_campos(
    sessoes: async_sessionmaker[AsyncSession],
) -> None:
    """001/R5.1"""
    async with sessoes() as sessao, sessao.begin():
        registro = await registrar(
            SqlAuditStore(sessao),
            acao="unidade.atualizada",
            entidade=Entidade(tipo="unidade", id="42"),
            mudancas=[Mudanca(campo="telefone", de="8133330000", para="8133331111")],
            ator=Ator(
                user_id=USUARIO,
                papeis=("GESTOR_DADOS",),
                session_id=SESSAO,
                ip="10.0.0.1",
                request_id="req-1",
            ),
            metadados={"user_agent": "teste"},
        )

    [linha] = await _trilha(sessoes)
    assert linha["action"] == "unidade.atualizada"
    assert (linha["entity_type"], linha["entity_id"]) == ("unidade", "42")
    assert linha["changes"] == [{"campo": "telefone", "de": "8133330000", "para": "8133331111"}]
    assert linha["actor_user_id"] == USUARIO
    assert linha["actor_roles"] == ["GESTOR_DADOS"]
    assert (linha["session_id"], linha["ip"], linha["request_id"]) == (SESSAO, "10.0.0.1", "req-1")
    assert linha["metadata"] == {"user_agent": "teste"}
    assert linha["hash"] == registro.hash
    assert linha["occurred_at"] == registro.occurred_at


async def test_falha_no_caso_de_uso_desfaz_a_auditoria(
    sessoes: async_sessionmaker[AsyncSession],
) -> None:
    """001/R5.1"""

    async def caso_de_uso_que_falha_depois_de_auditar() -> None:
        async with sessoes() as sessao, sessao.begin():
            await registrar(SqlAuditStore(sessao), acao="unidade.atualizada", ator=Ator())
            raise FalhaSimuladaError

    with pytest.raises(FalhaSimuladaError):
        await caso_de_uso_que_falha_depois_de_auditar()

    assert await _trilha(sessoes) == []
    assert await _cabeca(sessoes) == GENESIS_HASH


async def test_cada_registro_encadeia_no_anterior(
    sessoes: async_sessionmaker[AsyncSession],
) -> None:
    """001/R5.3"""
    for acao in ("unidade.criada", "unidade.atualizada", "auth.login"):
        await _registrar(sessoes, acao)

    trilha = await _trilha(sessoes)
    assert [linha["action"] for linha in trilha] == [
        "unidade.criada",
        "unidade.atualizada",
        "auth.login",
    ]
    _assert_cadeia_integra(trilha, await _cabeca(sessoes))


async def test_transacoes_simultaneas_nao_bifurcam_a_cadeia(
    sessoes: async_sessionmaker[AsyncSession],
) -> None:
    """001/R5.3"""
    await asyncio.gather(*(_registrar(sessoes, f"teste.evento_{n}") for n in range(8)))

    trilha = await _trilha(sessoes)
    assert len(trilha) == 8
    _assert_cadeia_integra(trilha, await _cabeca(sessoes))
