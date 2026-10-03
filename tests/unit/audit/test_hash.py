"""Hash encadeado dos registros de auditoria (spec 001, R5.3)."""

import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import pytest
from hypothesis import given
from hypothesis import strategies as st

from src.core.errors import DomainValidationError
from src.modules.audit.domain.entry import GENESIS_HASH, Ator, AuditEntry, Entidade, Mudanca

QUANDO = datetime(2026, 10, 3, 12, 0, 0, 123456, tzinfo=UTC)
USUARIO = UUID("01928a3b-0000-7000-8000-000000000001")


def _registro(**alteracoes: Any) -> AuditEntry:
    campos: dict[str, Any] = {
        "prev_hash": GENESIS_HASH,
        "occurred_at": QUANDO,
        "action": "unidade.atualizada",
        "actor": Ator(user_id=USUARIO, papeis=("GESTOR_DADOS",), ip="10.0.0.1", request_id="r1"),
        "entity": Entidade(tipo="unidade", id="42"),
        "changes": (Mudanca(campo="telefone", de="8133330000", para="8133331111"),),
        "metadata": {"motivo": "atualização"},
    }
    return AuditEntry.create(**(campos | alteracoes))


def test_hash_e_sha256_do_hash_anterior_mais_o_conteudo_canonico() -> None:
    """001/R5.3"""
    canonico = (
        '{"action":"unidade.atualizada","actor_roles":["GESTOR_DADOS"],'
        '"actor_user_id":"01928a3b-0000-7000-8000-000000000001",'
        '"changes":[{"campo":"telefone","de":"8133330000","para":"8133331111"}],'
        '"entity_id":"42","entity_type":"unidade","ip":"10.0.0.1",'
        '"metadata":{"motivo":"atualização"},"occurred_at":"2026-10-03T12:00:00.123456+00:00",'
        '"request_id":"r1","session_id":null}'
    )

    registro = _registro()

    assert registro.canonical_content() == canonico.encode()
    assert registro.hash == hashlib.sha256((GENESIS_HASH + canonico).encode()).hexdigest()
    assert registro.recompute_hash() == registro.hash


VALORES_JSON = st.recursive(
    st.none()
    | st.booleans()
    | st.integers()
    | st.floats(allow_nan=False, allow_infinity=False)
    | st.text(max_size=20),
    lambda filhos: st.lists(filhos, max_size=3) | st.dictionaries(st.text(max_size=8), filhos),
    max_leaves=8,
)


@given(st.dictionaries(st.text(max_size=8), VALORES_JSON, min_size=2))
def test_hash_nao_depende_da_ordem_das_chaves(metadados: dict[str, Any]) -> None:
    """001/R5.3"""
    invertido = dict(reversed(list(metadados.items())))

    assert _registro(metadata=metadados).hash == _registro(metadata=invertido).hash


ALTERACOES: dict[str, dict[str, Any]] = {
    "prev_hash": {"prev_hash": "f" * 64},
    "occurred_at": {"occurred_at": QUANDO + timedelta(microseconds=1)},
    "action": {"action": "unidade.criada"},
    "actor": {"actor": Ator(user_id=USUARIO, papeis=("AUDITOR",), ip="10.0.0.1")},
    "entity": {"entity": Entidade(tipo="unidade", id="43")},
    "changes": {"changes": (Mudanca(campo="telefone", de="8133330000", para="0"),)},
    "metadata": {"metadata": {"motivo": "outro"}},
}


@pytest.mark.parametrize("alteracao", ALTERACOES.values(), ids=ALTERACOES.keys())
def test_qualquer_campo_alterado_muda_o_hash(alteracao: dict[str, Any]) -> None:
    """001/R5.3"""
    assert _registro(**alteracao).hash != _registro().hash


def test_registro_adulterado_nao_confere_com_o_hash() -> None:
    """001/R5.3"""
    adulterado = replace(_registro(), action="unidade.removida")

    assert adulterado.recompute_hash() != adulterado.hash


def test_mesmo_instante_em_outro_fuso_gera_o_mesmo_hash() -> None:
    """001/R5.3 (datas sempre em UTC no conteúdo canônico)"""
    recife = timezone(timedelta(hours=-3))

    assert _registro(occurred_at=QUANDO.astimezone(recife)).hash == _registro().hash


@pytest.mark.parametrize(
    "invalido",
    [
        {"occurred_at": datetime(2026, 10, 3, 12, 0)},  # noqa: DTZ001 - sem fuso de propósito
        {"action": "UnidadeAtualizada"},
        {"prev_hash": "abc"},
        {"metadata": {"valor": float("nan")}},
    ],
)
def test_registro_invalido_e_recusado(invalido: dict[str, Any]) -> None:
    """001/R5.3"""
    with pytest.raises(DomainValidationError):
        _registro(**invalido)


def test_ip_do_ator_e_validado_e_normalizado() -> None:
    """001/R5.3 (o IP entra no hash; a forma normalizada evita dois textos para o mesmo IP)"""
    with pytest.raises(DomainValidationError):
        Ator(ip="999.1.1.1")
    assert Ator(ip="2001:DB8:0:0:0:0:0:1").ip == "2001:db8::1"
