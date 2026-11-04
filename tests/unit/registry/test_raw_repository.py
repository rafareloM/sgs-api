"""Testes das operações com SQL explícito usadas na Etapa 03."""

from collections.abc import Mapping
from typing import Any
from unittest.mock import AsyncMock, Mock

from sqlalchemy.sql.elements import TextClause

from src.modules.registry.infrastructure.raw_repository import SqlEtapa3Repository


def _result(row: Mapping[str, Any]) -> Mock:
    result = Mock()
    result.mappings.return_value.one.return_value = row
    result.mappings.return_value.one_or_none.return_value = row
    return result


async def test_criar_unidade_grava_dados_e_auditoria_com_text() -> None:
    session = AsyncMock()
    session.execute.return_value = _result(
        {
            "idunidade": 3,
            "codigocnes": None,
            "nome": "UBS São João",
            "tipo": "UBS",
            "endereco": "Rua A",
            "cep": "50000000",
            "distritosanitario": "Centro",
            "telefone": None,
            "status": "Ativa",
            "datacriacao": None,
            "dataatualizacao": None,
            "cnes_pendente": True,
            "versao": 1,
        }
    )
    repository = SqlEtapa3Repository(session)

    await repository.create_unidade(
        {
            "codigocnes": None,
            "nome": "UBS São João",
            "tipo": "UBS",
            "endereco": "Rua A",
            "cep": "50000000",
            "distritosanitario": "Centro",
            "telefone": None,
            "status": "Ativa",
            "cnes_pendente": True,
        },
        autor_id=9,
    )

    assert session.execute.await_count == 2
    insert, parametros = session.execute.await_args_list[0].args
    assert isinstance(insert, TextClause)
    assert "INSERT INTO unidade_saude" in str(insert)
    assert parametros["nomenormalizado"] == "ubs sao joao"
    auditoria, registros = session.execute.await_args_list[1].args
    assert isinstance(auditoria, TextClause)
    assert "INSERT INTO alteracao" in str(auditoria)
    assert all(registro["idusuario"] == 9 for registro in registros)
    assert all(registro["idunidade"] == 3 for registro in registros)


async def test_patch_status_audita_valores_e_motivo_na_mesma_sessao() -> None:
    session = AsyncMock()
    atualizado = {"idunidade": 3, "status": "Inativa", "versao": 2}
    session.execute.side_effect = [
        _result({"status": "Ativa", "versao": 1}),
        _result(atualizado),
        Mock(),
    ]
    repository = SqlEtapa3Repository(session)

    result = await repository.update_status(3, "Inativa", 1, 9, "Unidade fechada")

    assert result == atualizado
    assert session.execute.await_count == 3
    update_query, _ = session.execute.await_args_list[1].args
    assert isinstance(update_query, TextClause)
    assert "versao = versao + 1" in str(update_query)
    audit_query, parametros = session.execute.await_args_list[2].args
    assert isinstance(audit_query, TextClause)
    assert "INSERT INTO alteracao" in str(audit_query)
    assert parametros == {
        "campo": "Status",
        "anterior": "Ativa",
        "novo": "Inativa",
        "idunidade": 3,
        "idusuario": 9,
        "motivo": "Unidade fechada",
    }
