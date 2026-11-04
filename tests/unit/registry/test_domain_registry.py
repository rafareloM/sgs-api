"""Testes unitários das entidades de domínio de cadastro (UnidadeSaude, Equipamento)."""

from datetime import UTC, datetime

import pytest

from src.core.errors import DomainValidationError
from src.modules.registry.domain.equipamento import Equipamento
from src.modules.registry.domain.unidade import UnidadeSaude, normalizar_nome


def test_unidade_saude_valida() -> None:
    unidade = UnidadeSaude(
        codigo_cnes="1000001",
        nome="UBS Vila da Paz",
        tipo="UBS",
        endereco="Rua do Sol, 150",
        cep="50010100",
        distrito_sanitario="Afogados",
        telefone="(81) 3321-1001",
        status="Ativa",
    )
    assert unidade.codigo_cnes == "1000001"
    assert unidade.tipo == "UBS"
    assert unidade.status == "Ativa"


def test_normaliza_nome_para_comparacao_de_unicidade() -> None:
    assert normalizar_nome("  UBS   São João  ") == "ubs sao joao"


@pytest.mark.parametrize("cnes", ["123456", "12345678", "abcdefg", "123 456"])
def test_unidade_recusa_cnes_invalido(cnes: str) -> None:
    with pytest.raises(DomainValidationError) as exc:
        UnidadeSaude(
            codigo_cnes=cnes,
            nome="UBS Teste",
            tipo="UBS",
            endereco="Rua Teste, 1",
            cep="50010100",
            distrito_sanitario="Centro",
            status="Ativa",
        )
    assert any(err.campo == "codigo_cnes" for err in exc.value.errors)


@pytest.mark.parametrize("cep", ["1234567", "123456789", "50010-100", "abcdefgh"])
def test_unidade_recusa_cep_invalido(cep: str) -> None:
    with pytest.raises(DomainValidationError) as exc:
        UnidadeSaude(
            codigo_cnes="1000001",
            nome="UBS Teste",
            tipo="UBS",
            endereco="Rua Teste, 1",
            cep=cep,
            distrito_sanitario="Centro",
            status="Ativa",
        )
    assert any(err.campo == "cep" for err in exc.value.errors)


def test_unidade_recusa_tipo_invalido() -> None:
    with pytest.raises(DomainValidationError) as exc:
        UnidadeSaude(
            codigo_cnes="1000001",
            nome="UBS Teste",
            tipo="Clínica Privada",
            endereco="Rua Teste, 1",
            cep="50010100",
            distrito_sanitario="Centro",
            status="Ativa",
        )
    assert any(err.campo == "tipo" for err in exc.value.errors)


def test_unidade_recusa_status_invalido() -> None:
    with pytest.raises(DomainValidationError) as exc:
        UnidadeSaude(
            codigo_cnes="1000001",
            nome="UBS Teste",
            tipo="UBS",
            endereco="Rua Teste, 1",
            cep="50010100",
            distrito_sanitario="Centro",
            status="Fechada Definitivamente",
        )
    assert any(err.campo == "status" for err in exc.value.errors)


def test_unidade_recusa_datas_inconsistentes() -> None:
    criacao = datetime(2025, 5, 10, 10, 0, 0, tzinfo=UTC)
    atualizacao = datetime(2025, 5, 1, 10, 0, 0, tzinfo=UTC)
    with pytest.raises(DomainValidationError) as exc:
        UnidadeSaude(
            codigo_cnes="1000001",
            nome="UBS Teste",
            tipo="UBS",
            endereco="Rua Teste, 1",
            cep="50010100",
            distrito_sanitario="Centro",
            status="Ativa",
            data_criacao=criacao,
            data_atualizacao=atualizacao,
        )
    assert any(err.campo == "data_atualizacao" for err in exc.value.errors)


def test_equipamento_valido() -> None:
    equip = Equipamento(
        nome="Respirador UTI",
        tipo="Respirador",
        quantidade=10,
        id_unidade=1,
    )
    assert equip.nome == "Respirador UTI"
    assert equip.quantidade == 10


def test_equipamento_pode_existir_sem_unidade() -> None:
    equipamento = Equipamento(
        nome="UTI móvel",
        tipo="Respirador",
        quantidade=1,
        id_unidade=None,
    )

    assert equipamento.id_unidade is None


def test_equipamento_recusa_tipo_invalido() -> None:
    with pytest.raises(DomainValidationError) as exc:
        Equipamento(
            nome="Bisturi elétrico",
            tipo="Tipo Inexistente",
            quantidade=5,
            id_unidade=1,
        )
    assert any(err.campo == "tipo" for err in exc.value.errors)


@pytest.mark.parametrize("qtd", [-1, 5001, 10000])
def test_equipamento_recusa_quantidade_fora_da_faixa(qtd: int) -> None:
    with pytest.raises(DomainValidationError) as exc:
        Equipamento(
            nome="Balança",
            tipo="Balança",
            quantidade=qtd,
            id_unidade=1,
        )
    assert any(err.campo == "quantidade" for err in exc.value.errors)
