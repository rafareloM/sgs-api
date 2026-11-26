"""`ArmazenamentoDeObjetos` em S3 com o boto3 (spec 005, R2.1 a R2.4, R2.7, R2.8, R3.2 e R3.6).

Design § Adaptador S3:
- **Credenciais por operação (D005-2).** Antes de cada envio, remoção ou URL, um `AssumeRole` com
  `RoleSessionName=sgs-{usuario_id}`, `ExternalId` e 900 s, e um cliente S3 só para aquela
  operação. Sem `RefreshableCredentials`: a sessão de 15 minutos cairia na janela de renovação do
  botocore. O STS usa a identidade do ambiente de execução, nunca chave fixa (R2.2). Sem papel
  (só fora de `prod`, 005/T4), valem as chaves do laboratório.
- **Dois endereços (D005-3).** O envio usa o endereço interno; a URL, o público, porque a
  assinatura SigV4 cobre o `host` (R3.6).
- **Checksum explícito (D005-14).** `when_required` nos dois sentidos, com o `ChecksumSHA256`
  enviado: o CRC32 em *trailer* dos padrões novos do SDK quebra armazenamentos compatíveis.

Toda chamada do boto3 roda numa *thread*. Nenhuma URL pré-assinada, chave de acesso ou credencial
vai para log ou mensagem de erro, nem com `LOG_LEVEL=DEBUG` (`_silenciar_o_sdk`).
"""

import logging
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Any, BinaryIO, Literal, get_args

import boto3
from anyio import to_thread
from botocore.config import Config

from src.modules.reports.domain.armazenamento import (
    DURACAO_DA_SESSAO_SEGUNDOS,
    VALIDADE_DA_URL_SEGUNDOS,
    ObjetoGravado,
    Sse,
    UrlAssinada,
    tipo_de_conteudo,
)

EstiloDeEndereco = Literal["virtual", "path"]

# `RoleSessionName` aceita de 2 a 64 caracteres de [\w+=,.@-]; o prefixo "sgs-" usa 4.
_SESSAO = re.compile(r"[\w+=,.@-]{1,60}", re.ASCII)
# Vai entre aspas no Content-Disposition: nada de aspas, barras ou quebras de linha.
_NOME_DO_ARQUIVO = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*\.([a-z0-9]+)", re.ASCII)
# Em DEBUG, o botocore registra a resposta do STS (com as credenciais temporárias), os cabeçalhos
# assinados e o pedido canônico com a assinatura, que bastam para remontar a URL pré-assinada; o
# urllib3 registra a linha de cada pedido. O filtro de `src/core/logging.py` não reconhece esses
# textos, e `LOG_LEVEL=DEBUG` é aceito em qualquer ambiente.
_LOGGERS_DO_SDK = ("boto3", "botocore", "urllib3")


@dataclass(frozen=True)
class ConfiguracaoS3:
    """Os campos `S3_*` de design § Configuração. A composição na raiz monta este objeto a partir
    do `Settings` (005/T4 e T6), que já recusa o que `prod` não aceita (R2.9)."""

    bucket: str
    regiao: str
    sse: Sse
    endpoint_url: str | None = None  # S3_ENDPOINT_URL: interno, usado no envio
    public_endpoint_url: str | None = None  # S3_PUBLIC_ENDPOINT_URL: o das URLs (padrão: o interno)
    ca_file: str | None = None  # S3_CA_FILE; sem ele, as CAs do sistema
    addressing_style: EstiloDeEndereco = "virtual"
    assume_role_arn: str | None = None
    external_id: str | None = field(default=None, repr=False)
    kms_key_id: str | None = None  # ARN da chave, com aws:kms (D005-5)
    access_key_id: str | None = field(default=None, repr=False)  # só laboratório
    secret_access_key: str | None = field(default=None, repr=False)  # só laboratório

    def __post_init__(self) -> None:
        if not self.bucket:
            raise ValueError("informe o S3_BUCKET")
        if self.sse not in get_args(Sse):
            raise ValueError("S3_SSE deve ser aws:kms ou AES256 (R2.3)")
        if self.addressing_style not in get_args(EstiloDeEndereco):
            raise ValueError("S3_ADDRESSING_STYLE deve ser virtual ou path")
        for nome, endereco in (
            ("S3_ENDPOINT_URL", self.endpoint_url),
            ("S3_PUBLIC_ENDPOINT_URL", self.public_endpoint_url),
        ):
            if endereco is not None and not endereco.startswith("https://"):
                raise ValueError(f"{nome} precisa usar https:// (R2.7)")
        if self.assume_role_arn is not None and not self.external_id:
            raise ValueError("o papel S3_ASSUME_ROLE_ARN exige o ExternalId (R2.1)")
        if self.assume_role_arn is None and not (self.access_key_id and self.secret_access_key):
            raise ValueError(
                "sem credencial para o S3: informe o S3_ASSUME_ROLE_ARN ou, fora de prod, "
                "as chaves do laboratório"
            )


def _agora() -> datetime:
    return datetime.now(UTC)


def _silenciar_o_sdk() -> None:
    """Deixa os registros do SDK em WARNING ou acima, como os do httpx em `src/core/logging.py`,
    sem baixar o nível de quem já está acima disso."""
    for nome in _LOGGERS_DO_SDK:
        logger = logging.getLogger(nome)
        logger.setLevel(max(logger.getEffectiveLevel(), logging.WARNING))


def _novo_cliente(servico: str, **parametros: Any) -> Any:
    """Uma `Session` por cliente: a `Session` do boto3 não é segura entre *threads*; o cliente é."""
    return boto3.session.Session().client(servico, **parametros)


class S3ArmazenamentoDeObjetos:
    """S3 da AWS ou compatível (SeaweedFS no laboratório, ADR-0005)."""

    def __init__(
        self,
        configuracao: ConfiguracaoS3,
        *,
        novo_cliente: Callable[..., Any] = _novo_cliente,
        relogio: Callable[[], datetime] = _agora,
    ) -> None:
        _silenciar_o_sdk()
        self._cfg = configuracao
        self._novo_cliente = novo_cliente
        self._relogio = relogio
        self._config_s3 = Config(
            # Só `S3_ENDPOINT_URL` escolhe o endereço: sem isto, `AWS_ENDPOINT_URL*` do ambiente
            # ou do arquivo compartilhado desviaria o cliente, até para `http://` (R2.7).
            ignore_configured_endpoint_urls=True,
            signature_version="s3v4",
            retries={"mode": "standard"},
            s3={"addressing_style": configuracao.addressing_style},
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
        )

    async def enviar(
        self,
        key: str,
        arquivo: BinaryIO,
        *,
        content_type: str,
        sha256_b64: str,
        metadados: Mapping[str, str],
        sessao: str,
    ) -> ObjetoGravado:
        enviar = partial(
            self._enviar,
            key,
            arquivo,
            content_type=content_type,
            sha256_b64=sha256_b64,
            metadados=metadados,
            sessao=sessao,
        )
        return await to_thread.run_sync(enviar)

    async def remover(self, key: str, version_id: str | None, *, sessao: str) -> None:
        await to_thread.run_sync(partial(self._remover, key, version_id, sessao=sessao))

    async def url_de_download(self, key: str, *, nome: str, sessao: str) -> UrlAssinada:
        return await to_thread.run_sync(
            partial(self._url_de_download, key, nome=nome, sessao=sessao)
        )

    def _enviar(
        self,
        key: str,
        arquivo: BinaryIO,
        *,
        content_type: str,
        sha256_b64: str,
        metadados: Mapping[str, str],
        sessao: str,
    ) -> ObjetoGravado:
        parametros: dict[str, Any] = {
            "Bucket": self._cfg.bucket,
            "Key": key,
            "Body": arquivo,
            "ContentType": content_type,
            "ServerSideEncryption": self._cfg.sse,
            "ChecksumSHA256": sha256_b64,
            "Metadata": dict(metadados),
        }
        if self._cfg.sse == "aws:kms" and self._cfg.kms_key_id:
            parametros["SSEKMSKeyId"] = self._cfg.kms_key_id
        resposta = self._cliente_s3(self._cfg.endpoint_url, sessao).put_object(**parametros)
        return ObjetoGravado(
            key=key,
            version_id=resposta.get("VersionId"),
            sse=resposta.get("ServerSideEncryption"),
            kms_key_id=resposta.get("SSEKMSKeyId"),
            checksum_sha256=resposta.get("ChecksumSHA256"),
        )

    def _remover(self, key: str, version_id: str | None, *, sessao: str) -> None:
        """Pela versão, num bucket versionado, para a versão ruim não ficar atrás de um *delete
        marker* (R2.8). Sem `VersionId` na resposta, o bucket não tem versionamento."""
        parametros: dict[str, Any] = {"Bucket": self._cfg.bucket, "Key": key}
        if version_id is not None:
            parametros["VersionId"] = version_id
        self._cliente_s3(self._cfg.endpoint_url, sessao).delete_object(**parametros)

    def _url_de_download(self, key: str, *, nome: str, sessao: str) -> UrlAssinada:
        tipo = _tipo_do_arquivo(nome)
        cliente = self._cliente_s3(self._cfg.public_endpoint_url or self._cfg.endpoint_url, sessao)
        # Antes de assinar: a URL vence alguns milissegundos depois do `expira_em` informado.
        expira_em = self._relogio() + timedelta(seconds=VALIDADE_DA_URL_SEGUNDOS)
        url = cliente.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": self._cfg.bucket,
                "Key": key,
                "ResponseContentDisposition": f'attachment; filename="{nome}"',
                "ResponseContentType": tipo,
            },
            ExpiresIn=VALIDADE_DA_URL_SEGUNDOS,
        )
        return UrlAssinada(url=url, expira_em=expira_em)

    def _cliente_s3(self, endpoint_url: str | None, sessao: str) -> Any:
        return self._novo_cliente(
            "s3",
            region_name=self._cfg.regiao,
            endpoint_url=endpoint_url,
            config=self._config_s3,
            verify=self._cfg.ca_file,
            **self._credenciais(sessao),
        )

    def _credenciais(self, sessao: str) -> dict[str, str]:
        """Credenciais temporárias de 15 minutos para esta operação (R2.1, D005-2)."""
        if not _SESSAO.fullmatch(sessao):
            raise ValueError("sessão fora do padrão do RoleSessionName do STS")
        if self._cfg.assume_role_arn is None:
            # `ConfiguracaoS3` garante as duas chaves quando não há papel.
            return {
                "aws_access_key_id": self._cfg.access_key_id or "",
                "aws_secret_access_key": self._cfg.secret_access_key or "",
            }
        sts = self._novo_cliente(
            "sts",
            region_name=self._cfg.regiao,
            config=Config(retries={"mode": "standard"}, ignore_configured_endpoint_urls=True),
        )
        credenciais = sts.assume_role(
            RoleArn=self._cfg.assume_role_arn,
            RoleSessionName=f"sgs-{sessao}",
            ExternalId=self._cfg.external_id,
            DurationSeconds=DURACAO_DA_SESSAO_SEGUNDOS,
        )["Credentials"]
        return {
            "aws_access_key_id": credenciais["AccessKeyId"],
            "aws_secret_access_key": credenciais["SecretAccessKey"],
            "aws_session_token": credenciais["SessionToken"],
        }


def _tipo_do_arquivo(nome: str) -> str:
    """O nome vai no `Content-Disposition`; o tipo sai da extensão (R1.2)."""
    encontrado = _NOME_DO_ARQUIVO.fullmatch(nome)
    if encontrado is None:
        raise ValueError("nome do arquivo fora do padrão")
    try:
        return tipo_de_conteudo(encontrado.group(1))
    except ValueError:
        raise ValueError("nome do arquivo fora do padrão") from None
