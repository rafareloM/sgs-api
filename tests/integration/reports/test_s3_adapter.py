"""Adaptador S3 dos relatórios com `moto` (005/T3; design § Adaptador S3, D005-2, D005-3, D005-14).

O `moto` 5.2 não devolve `ChecksumSHA256` na resposta do `PutObject` (design § Riscos). A AWS e os
compatíveis devolvem o checksum enviado; o teste faz esse papel pelo evento
`after-call.s3.PutObject` do botocore, que também simula a resposta sem SSE da R2.8.
"""

import hashlib
import io
import logging
import uuid
from base64 import b64encode
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import boto3
import pytest
from moto import mock_aws

from src.modules.reports.domain.armazenamento import (
    VALIDADE_DA_URL_SEGUNDOS,
    GravacaoEsperada,
    conferir_gravacao,
)
from src.modules.reports.infrastructure.s3_storage import ConfiguracaoS3, S3ArmazenamentoDeObjetos

BUCKET = "sgs-relatorios"
REGIAO = "us-east-1"
INTERNO = "https://s3.interno.test:8333"
PUBLICO = "https://s3.localhost"
PAPEL = "arn:aws:iam::123456789012:role/sgs-relatorios"
EXTERNAL_ID = "sgs-external-id-de-teste"
KMS = "arn:aws:kms:us-east-1:123456789012:key/1234abcd-12ab-34cd-56ef-1234567890ab"
CHAVE_LAB = "sgs-lab-exemplo"
SEGREDO_LAB = "sgs-lab-exemplo-s3"
SOLICITANTE = uuid.UUID("5d1c1a9e-0f3b-4d6e-8a2b-3c4d5e6f7a8b")
QUEM_BAIXA = uuid.UUID("7e2d2b0f-1a4c-4e7f-9b3c-4d5e6f7a8b9c")
AGORA = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)
CONTEUDO = "cnes;nome\r\n1000001;USF Alto do Céu\r\n".encode() * 100
SHA = b64encode(hashlib.sha256(CONTEUDO).digest()).decode()
KEY = f"reports/2026/11/inventario_unidades/{uuid.uuid4()}.csv"
METADADOS = {"sgs-sha256": SHA, "sgs-kid": "rel-2026-11-25", "sgs-assinatura": "abc"}


@dataclass
class Bastidores:
    """Fábrica de clientes que grava o que o adaptador pede ao boto3 e o que o S3 responde."""

    clientes: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    papeis: list[dict[str, Any]] = field(default_factory=list)
    chaves_emitidas: list[str] = field(default_factory=list)
    segredos_emitidos: list[str] = field(default_factory=list)
    envios: list[dict[str, str]] = field(default_factory=list)
    ajustar_resposta: Callable[[dict[str, Any]], None] = lambda _: None

    def novo_cliente(self, servico: str, **parametros: Any) -> Any:
        self.clientes.append((servico, parametros))
        cliente = boto3.session.Session().client(servico, **parametros)
        eventos = cliente.meta.events
        eventos.register("before-parameter-build.sts.AssumeRole", self._papel_pedido)
        eventos.register("after-call.sts.AssumeRole", self._papel_emitido)
        eventos.register_first("before-send.s3.PutObject", self._envio)
        eventos.register("after-call.s3.PutObject", self._resposta)
        return cliente

    def clientes_de(self, servico: str) -> list[dict[str, Any]]:
        return [parametros for nome, parametros in self.clientes if nome == servico]

    def _papel_pedido(self, params: dict[str, Any], **_: Any) -> None:
        self.papeis.append(dict(params))

    def _papel_emitido(self, parsed: dict[str, Any], **_: Any) -> None:
        credenciais = parsed["Credentials"]
        self.chaves_emitidas.append(credenciais["AccessKeyId"])
        self.segredos_emitidos += [credenciais["SecretAccessKey"], credenciais["SessionToken"]]

    def _envio(self, request: Any, **_: Any) -> None:
        self.envios.append(
            {
                k.lower(): v.decode() if isinstance(v, bytes) else v
                for k, v in request.headers.items()
            }
        )

    def _resposta(self, parsed: dict[str, Any], **_: Any) -> None:
        parsed.setdefault("ChecksumSHA256", self.envios[-1]["x-amz-checksum-sha256"])
        self.ajustar_resposta(parsed)


@pytest.fixture
def s3_falso(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """S3 e STS do `moto`. A identidade do ambiente (papel da instância, em prod) é a do moto."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "identidade-do-ambiente")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "identidade-do-ambiente")
    monkeypatch.delenv("AWS_SESSION_TOKEN", raising=False)
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    monkeypatch.setenv("MOTO_S3_CUSTOM_ENDPOINTS", f"{INTERNO},{PUBLICO}")
    with mock_aws():
        s3 = boto3.session.Session().client("s3", region_name=REGIAO, endpoint_url=INTERNO)
        s3.create_bucket(Bucket=BUCKET)
        s3.put_bucket_versioning(Bucket=BUCKET, VersioningConfiguration={"Status": "Enabled"})
        yield s3


def _configuracao(**campos: Any) -> ConfiguracaoS3:
    padrao: dict[str, Any] = {
        "bucket": BUCKET,
        "regiao": REGIAO,
        "sse": "AES256",
        "endpoint_url": INTERNO,
        "public_endpoint_url": PUBLICO,
        "addressing_style": "path",
        "assume_role_arn": PAPEL,
        "external_id": EXTERNAL_ID,
    }
    return ConfiguracaoS3(**(padrao | campos))


def _adaptador(bastidores: Bastidores, **campos: Any) -> S3ArmazenamentoDeObjetos:
    return S3ArmazenamentoDeObjetos(
        _configuracao(**campos), novo_cliente=bastidores.novo_cliente, relogio=lambda: AGORA
    )


async def _enviar(adaptador: S3ArmazenamentoDeObjetos, sessao: uuid.UUID = SOLICITANTE) -> Any:
    return await adaptador.enviar(
        KEY,
        io.BytesIO(CONTEUDO),
        content_type="text/csv; charset=utf-8",
        sha256_b64=SHA,
        metadados=METADADOS,
        sessao=str(sessao),
    )


async def test_envio_assume_o_papel_com_external_id_e_a_sessao_de_quem_pediu(s3_falso: Any) -> None:
    """005/R2.1"""
    bastidores = Bastidores()

    await _enviar(_adaptador(bastidores))

    assert bastidores.papeis == [
        {
            "RoleArn": PAPEL,
            "RoleSessionName": f"sgs-{SOLICITANTE}",
            "ExternalId": EXTERNAL_ID,
            "DurationSeconds": 900,
        }
    ]
    (sts,) = bastidores.clientes_de("sts")
    assert "aws_access_key_id" not in sts  # o STS usa a identidade do ambiente, nunca chave fixa
    (s3,) = bastidores.clientes_de("s3")
    assert s3["aws_access_key_id"] == bastidores.chaves_emitidas[0]
    assert s3["aws_session_token"]


async def test_envio_grava_com_sse_checksum_metadados_e_a_chave_pedida(s3_falso: Any) -> None:
    """005/R2.3, 005/R2.4, 005/R2.8"""
    bastidores = Bastidores()

    gravado = await _enviar(_adaptador(bastidores))

    (cabecalhos,) = bastidores.envios
    assert cabecalhos["x-amz-server-side-encryption"] == "AES256"
    assert cabecalhos["x-amz-checksum-sha256"] == SHA
    # D005-14: só o checksum explícito, sem o CRC32 em trailer dos padrões novos do SDK.
    assert not {"x-amz-trailer", "x-amz-sdk-checksum-algorithm", "x-amz-checksum-crc32"} & set(
        cabecalhos
    )
    objeto = s3_falso.head_object(Bucket=BUCKET, Key=KEY)
    assert objeto["ServerSideEncryption"] == "AES256"
    assert objeto["ContentType"] == "text/csv; charset=utf-8"
    assert objeto["Metadata"] == METADADOS
    assert gravado.key == KEY
    assert gravado.version_id == objeto["VersionId"]
    assert gravado.sse == "AES256"
    assert gravado.checksum_sha256 == SHA
    esperada = GravacaoEsperada(sse="AES256", kms_key_id=None, sha256_b64=SHA)
    assert conferir_gravacao(esperada, gravado) == []


async def test_envio_com_kms_manda_a_chave_e_a_resposta_confere(s3_falso: Any) -> None:
    """005/R2.3, 005/R2.8 (D005-5)"""
    bastidores = Bastidores()

    gravado = await _enviar(_adaptador(bastidores, sse="aws:kms", kms_key_id=KMS))

    (cabecalhos,) = bastidores.envios
    assert cabecalhos["x-amz-server-side-encryption"] == "aws:kms"
    assert cabecalhos["x-amz-server-side-encryption-aws-kms-key-id"] == KMS
    assert (gravado.sse, gravado.kms_key_id) == ("aws:kms", KMS)
    esperada = GravacaoEsperada(sse="aws:kms", kms_key_id=KMS, sha256_b64=SHA)
    assert conferir_gravacao(esperada, gravado) == []


async def test_resposta_sem_sse_nao_confere_e_a_versao_gravada_e_removida(s3_falso: Any) -> None:
    """005/R2.8: remoção pela versão, sem deixar a versão ruim atrás de um delete marker."""
    bastidores = Bastidores(ajustar_resposta=lambda resposta: resposta.pop("ServerSideEncryption"))
    adaptador = _adaptador(bastidores)

    gravado = await _enviar(adaptador)
    problemas = conferir_gravacao(GravacaoEsperada("AES256", None, SHA), gravado)
    await adaptador.remover(gravado.key, gravado.version_id, sessao=str(SOLICITANTE))

    assert problemas == ["sse"]
    assert gravado.version_id
    versoes = s3_falso.list_object_versions(Bucket=BUCKET, Prefix=KEY)
    assert "Versions" not in versoes
    assert "DeleteMarkers" not in versoes
    assert [p["RoleSessionName"] for p in bastidores.papeis] == [f"sgs-{SOLICITANTE}"] * 2


async def test_remover_sem_versao_apaga_o_objeto_num_bucket_sem_versionamento(
    s3_falso: Any,
) -> None:
    """005/R2.8"""
    s3_falso.create_bucket(Bucket="sem-versao")
    bastidores = Bastidores()
    adaptador = _adaptador(bastidores, bucket="sem-versao")

    gravado = await _enviar(adaptador)
    await adaptador.remover(gravado.key, gravado.version_id, sessao=str(SOLICITANTE))

    assert gravado.version_id is None
    assert "Contents" not in s3_falso.list_objects_v2(Bucket="sem-versao")


async def test_url_usa_o_endereco_publico_vale_300s_e_baixa_como_anexo(s3_falso: Any) -> None:
    """005/R3.2, 005/R3.6"""
    bastidores = Bastidores()
    adaptador = _adaptador(bastidores)
    nome = "sgs-inventario_unidades-2026-11-25.csv"

    assinada = await adaptador.url_de_download(KEY, nome=nome, sessao=str(QUEM_BAIXA))

    partes = urlsplit(assinada.url)
    consulta = parse_qs(partes.query)
    assert (partes.scheme, partes.hostname) == ("https", "s3.localhost")
    assert "s3.interno.test" not in assinada.url
    assert partes.path == f"/{BUCKET}/{KEY}"
    assert consulta["X-Amz-Expires"] == [str(VALIDADE_DA_URL_SEGUNDOS)] == ["300"]
    assert consulta["response-content-disposition"] == [f'attachment; filename="{nome}"']
    assert consulta["response-content-type"] == ["text/csv; charset=utf-8"]
    assert consulta["X-Amz-Security-Token"]  # assinada com a credencial temporária
    assert assinada.expira_em == AGORA + timedelta(seconds=300)
    assert [p["RoleSessionName"] for p in bastidores.papeis] == [f"sgs-{QUEM_BAIXA}"]
    (s3,) = bastidores.clientes_de("s3")
    assert s3["endpoint_url"] == PUBLICO


async def test_cada_operacao_assume_o_papel_de_novo_com_o_usuario_dela(s3_falso: Any) -> None:
    """005/R2.1 (D005-2: sem credencial de longa duração; a URL não vence antes da hora)"""
    bastidores = Bastidores()
    adaptador = _adaptador(bastidores)

    await _enviar(adaptador)
    await adaptador.url_de_download(KEY, nome="sgs-x-2026-11-25.csv", sessao=str(QUEM_BAIXA))

    assert [p["RoleSessionName"] for p in bastidores.papeis] == [
        f"sgs-{SOLICITANTE}",
        f"sgs-{QUEM_BAIXA}",
    ]
    envio, url = bastidores.clientes_de("s3")
    assert (envio["endpoint_url"], url["endpoint_url"]) == (INTERNO, PUBLICO)
    assert [envio["aws_access_key_id"], url["aws_access_key_id"]] == bastidores.chaves_emitidas
    assert len(set(bastidores.chaves_emitidas)) == 2


async def test_sem_papel_usa_as_chaves_do_laboratorio_e_nao_chama_o_sts(s3_falso: Any) -> None:
    """005/R2.2 (fora de prod; a recusa em prod é da configuração, 005/T4)"""
    bastidores = Bastidores()
    adaptador = _adaptador(
        bastidores,
        assume_role_arn=None,
        external_id=None,
        access_key_id=CHAVE_LAB,
        secret_access_key=SEGREDO_LAB,
    )

    await _enviar(adaptador)

    assert bastidores.clientes_de("sts") == []
    (s3,) = bastidores.clientes_de("s3")
    assert (s3["aws_access_key_id"], s3["aws_secret_access_key"]) == (CHAVE_LAB, SEGREDO_LAB)
    assert "aws_session_token" not in s3


async def test_clientes_conferem_a_ca_e_pedem_checksum_so_quando_exigido(
    s3_falso: Any, tmp_path: Path
) -> None:
    """005/R2.7 (D005-14)"""
    ca = tmp_path / "ca.crt"
    ca.write_text("CA de teste\n")
    bastidores = Bastidores()

    await _enviar(_adaptador(bastidores, ca_file=str(ca)))

    (sts,) = bastidores.clientes_de("sts")
    (s3,) = bastidores.clientes_de("s3")
    assert s3["verify"] == str(ca)
    assert s3["region_name"] == sts["region_name"] == REGIAO
    config = s3["config"]
    assert config.signature_version == "s3v4"
    assert config.s3 == {"addressing_style": "path"}
    assert config.request_checksum_calculation == "when_required"
    assert config.response_checksum_validation == "when_required"
    assert config.retries == {"mode": "standard"}


@pytest.mark.parametrize(
    ("campos", "mensagem"),
    [
        ({"endpoint_url": "http://s3:8333"}, "https"),
        ({"public_endpoint_url": "http://s3.localhost"}, "https"),
        ({"external_id": None}, "ExternalId"),
        ({"assume_role_arn": None, "external_id": None}, "credencial"),
        ({"sse": "nenhuma"}, "S3_SSE"),
        ({"addressing_style": "outro"}, "S3_ADDRESSING_STYLE"),
    ],
)
def test_configuracao_invalida_e_recusada(campos: dict[str, Any], mensagem: str) -> None:
    """005/R2.1, 005/R2.7"""
    with pytest.raises(ValueError, match=mensagem):
        _configuracao(**campos)


def test_segredos_e_url_nao_aparecem_no_repr() -> None:
    """steering/security.md: nenhuma chave em log ou exceção, nem por acidente."""
    configuracao = _configuracao(access_key_id=CHAVE_LAB, secret_access_key=SEGREDO_LAB)

    assert SEGREDO_LAB not in repr(configuracao)
    assert CHAVE_LAB not in repr(configuracao)


async def test_url_assinada_nao_aparece_no_repr(s3_falso: Any) -> None:
    """005/R3.2 e design § Segurança: a URL é uma credencial de 5 minutos, nunca em log."""
    adaptador = _adaptador(Bastidores())

    assinada = await adaptador.url_de_download(KEY, nome="sgs-x-2026-11-25.csv", sessao="1")

    assert assinada.url not in repr(assinada)
    assert "X-Amz-Signature" not in repr(assinada)


async def test_nem_em_debug_credencial_assinatura_ou_url_chegam_ao_log(
    s3_falso: Any, caplog: pytest.LogCaptureFixture
) -> None:
    """005/R2.1, 005/R3.2 (design § Segurança: credenciais e URL nunca vão para log).

    `LOG_LEVEL=DEBUG` é aceito em qualquer ambiente. Nesse nível, o botocore registra a resposta
    do STS, os cabeçalhos assinados e o pedido canônico com a assinatura, que o filtro de
    `src/core/logging.py` não reconhece."""
    caplog.set_level(logging.DEBUG)
    bastidores = Bastidores()
    adaptador = _adaptador(bastidores)

    gravado = await _enviar(adaptador)
    await adaptador.remover(gravado.key, gravado.version_id, sessao=str(SOLICITANTE))
    assinada = await adaptador.url_de_download(
        KEY, nome="sgs-x-2026-11-25.csv", sessao=str(QUEM_BAIXA)
    )
    logging.getLogger("sgs_api.teste").debug("marcador")

    (assinatura,) = parse_qs(urlsplit(assinada.url).query)["X-Amz-Signature"]
    segredos = [
        EXTERNAL_ID,
        assinada.url,
        assinatura,
        *bastidores.chaves_emitidas,
        *bastidores.segredos_emitidos,
    ]
    assert len(bastidores.segredos_emitidos) == 6  # envio, remoção e URL assumiram o papel
    assert "marcador" in caplog.text  # o caplog recebe registros de DEBUG
    vazados = [segredo[:12] for segredo in segredos if segredo in caplog.text]
    assert vazados == []


@pytest.mark.parametrize(
    "nome", ['a".csv', "a\r\nSet-Cookie: x.csv", "../a.csv", "sem-extensao", "a.pdf", ""]
)
async def test_url_recusa_nome_de_arquivo_que_quebraria_o_cabecalho(
    s3_falso: Any, nome: str
) -> None:
    """005/R3.2: o nome vai no Content-Disposition."""
    with pytest.raises(ValueError, match="nome do arquivo"):
        await _adaptador(Bastidores()).url_de_download(KEY, nome=nome, sessao="1")


@pytest.mark.parametrize("sessao", ["", "a b", "x" * 61, "usuário"])
async def test_sessao_fora_do_padrao_do_sts_e_recusada(s3_falso: Any, sessao: str) -> None:
    """005/R2.1: `RoleSessionName` aceita até 64 caracteres de [\\w+=,.@-]."""
    with pytest.raises(ValueError, match="sessão"):
        await _enviar_com_sessao(_adaptador(Bastidores()), sessao)


async def _enviar_com_sessao(adaptador: S3ArmazenamentoDeObjetos, sessao: str) -> Any:
    return await adaptador.enviar(
        KEY,
        io.BytesIO(CONTEUDO),
        content_type="text/csv; charset=utf-8",
        sha256_b64=SHA,
        metadados=METADADOS,
        sessao=sessao,
    )
