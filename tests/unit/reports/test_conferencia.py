"""Conferência da gravação e nomes do objeto (005/T3; design § Portas e adaptadores, § Download)."""

import uuid
from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from src.modules.reports.domain.armazenamento import (
    GravacaoEsperada,
    ObjetoGravado,
    chave_do_objeto,
    conferir_gravacao,
    nome_do_arquivo,
    tipo_de_conteudo,
)

SHA = "SEodYlxfXcVndv3gE2jglP5gRvF6pSW6e4cY4T9hDOc="
OUTRO_SHA = "47DEQpj8HBSa+/TImW+5JCeuQeRkm5NMpJWZG3hSuFU="
KMS = "arn:aws:kms:us-east-1:123456789012:key/1234abcd-12ab-34cd-56ef-1234567890ab"
OUTRA_KMS = "arn:aws:kms:us-east-1:123456789012:key/99999999-12ab-34cd-56ef-1234567890ab"
PEDIDO = uuid.UUID("0b6f7d3e-2c1a-4f5e-9d8c-7b6a5f4e3d2c")


def _gravado(**campos: str | None) -> ObjetoGravado:
    padrao: dict[str, str | None] = {
        "key": "reports/2026/11/inventario_unidades/x.csv",
        "version_id": "v1",
        "sse": "aws:kms",
        "kms_key_id": KMS,
        "checksum_sha256": SHA,
    }
    return ObjetoGravado(**(padrao | campos))  # type: ignore[arg-type]


def test_gravacao_que_confere_nao_tem_problemas() -> None:
    """005/R2.8"""
    esperada = GravacaoEsperada(sse="aws:kms", kms_key_id=KMS, sha256_b64=SHA)

    assert conferir_gravacao(esperada, _gravado()) == []


def test_aes256_sem_chave_kms_confere_so_sse_e_checksum() -> None:
    """005/R2.8 (dev: AES256, R2.3)"""
    esperada = GravacaoEsperada(sse="AES256", kms_key_id=None, sha256_b64=SHA)

    assert conferir_gravacao(esperada, _gravado(sse="AES256", kms_key_id=None)) == []


@pytest.mark.parametrize("sse", [None, "AES256", ""])
def test_sse_ausente_ou_diferente_nao_confere(sse: str | None) -> None:
    """005/R2.8"""
    esperada = GravacaoEsperada(sse="aws:kms", kms_key_id=KMS, sha256_b64=SHA)

    assert conferir_gravacao(esperada, _gravado(sse=sse)) == ["sse"]


@pytest.mark.parametrize("kms", [None, OUTRA_KMS, "alias/sgs-relatorios"])
def test_chave_kms_ausente_ou_diferente_nao_confere(kms: str | None) -> None:
    """005/R2.8 (D005-5: em prod a chave esperada é o ARN, e a resposta traz o ARN)"""
    esperada = GravacaoEsperada(sse="aws:kms", kms_key_id=KMS, sha256_b64=SHA)

    assert conferir_gravacao(esperada, _gravado(kms_key_id=kms)) == ["kms_key_id"]


@pytest.mark.parametrize("checksum", [None, OUTRO_SHA, ""])
def test_checksum_ausente_ou_diferente_nao_confere(checksum: str | None) -> None:
    """005/R2.8"""
    esperada = GravacaoEsperada(sse="aws:kms", kms_key_id=KMS, sha256_b64=SHA)

    assert conferir_gravacao(esperada, _gravado(checksum_sha256=checksum)) == ["checksum_sha256"]


def test_todos_os_campos_que_nao_conferem_sao_listados() -> None:
    """005/R2.8"""
    esperada = GravacaoEsperada(sse="aws:kms", kms_key_id=KMS, sha256_b64=SHA)
    gravado = _gravado(sse=None, kms_key_id=None, checksum_sha256=None)

    assert conferir_gravacao(esperada, gravado) == ["sse", "kms_key_id", "checksum_sha256"]


def test_chave_do_objeto_segue_o_formato_sem_dado_pessoal() -> None:
    """005/R2.4"""
    criado_em = datetime(2026, 3, 7, 23, 59, tzinfo=UTC)

    chave = chave_do_objeto(
        criado_em=criado_em, tipo="trilha_auditoria", pedido_id=PEDIDO, formato="xlsx"
    )

    assert chave == f"reports/2026/03/trilha_auditoria/{PEDIDO}.xlsx"


def test_chave_do_objeto_usa_o_mes_em_utc() -> None:
    """005/R2.4: o pedido criado às 22h de 31/03 em Recife (UTC-3) já é abril em UTC."""
    recife = timezone(timedelta(hours=-3))
    criado_em = datetime(2026, 3, 31, 22, 0, tzinfo=recife)

    chave = chave_do_objeto(
        criado_em=criado_em, tipo="inventario_unidades", pedido_id=PEDIDO, formato="csv"
    )

    assert chave.startswith("reports/2026/04/inventario_unidades/")


@pytest.mark.parametrize(
    ("tipo", "formato"),
    [("../x", "csv"), ("inventario_unidades", "csv/../x"), ("", "csv"), ("trilha", "pdf")],
)
def test_chave_do_objeto_recusa_tipo_ou_formato_fora_do_padrao(tipo: str, formato: str) -> None:
    """005/R2.4"""
    with pytest.raises(ValueError, match="tipo ou formato"):
        chave_do_objeto(
            criado_em=datetime(2026, 1, 1, tzinfo=UTC), tipo=tipo, pedido_id=PEDIDO, formato=formato
        )


def test_chave_do_objeto_exige_instante_com_fuso() -> None:
    """005/R2.4"""
    with pytest.raises(ValueError, match="fuso"):
        chave_do_objeto(
            criado_em=datetime(2026, 1, 1),  # noqa: DTZ001 - é o caso testado
            tipo="inventario_unidades",
            pedido_id=PEDIDO,
            formato="csv",
        )


def test_nome_do_arquivo_baixado_nao_traz_dado_pessoal() -> None:
    """005/R3.2 (design § Adaptador S3: `sgs-{tipo}-{aaaa-mm-dd}.{formato}`)"""
    nome = nome_do_arquivo(tipo="inventario_unidades", data=date(2026, 11, 5), formato="csv")

    assert nome == "sgs-inventario_unidades-2026-11-05.csv"


def test_tipo_de_conteudo_por_formato() -> None:
    """005/R1.2"""
    assert tipo_de_conteudo("csv") == "text/csv; charset=utf-8"
    assert tipo_de_conteudo("xlsx") == (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    with pytest.raises(ValueError, match="formato"):
        tipo_de_conteudo("pdf")
