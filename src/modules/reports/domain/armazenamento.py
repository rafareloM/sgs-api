"""Armazenamento dos arquivos dos relatórios (spec 005, R2 e R3.2; design § Portas e adaptadores).

A conferência da gravação (R2.8, D005-4) é uma função pura: compara o que a resposta do
armazenamento informa com o que foi pedido, em vez de confiar no cabeçalho enviado.
"""

import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import BinaryIO, Final, Literal, Protocol

VALIDADE_DA_URL_SEGUNDOS: Final = 300  # R3.2 fixa 5 minutos (D005-13)
DURACAO_DA_SESSAO_SEGUNDOS: Final = 900  # R2.1: credenciais de no máximo 15 minutos

Sse = Literal["aws:kms", "AES256"]

_TIPOS_DE_CONTEUDO: Final = {
    "csv": "text/csv; charset=utf-8",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
_TIPO_DE_RELATORIO = re.compile(r"[a-z][a-z_]*", re.ASCII)


@dataclass(frozen=True)
class GravacaoEsperada:
    sse: Sse
    kms_key_id: str | None  # ARN, em prod (D005-5)
    sha256_b64: str


@dataclass(frozen=True)
class ObjetoGravado:
    """O que a resposta do `PutObject` informa (R2.8), não o que foi pedido."""

    key: str
    version_id: str | None
    sse: str | None  # ServerSideEncryption da resposta
    kms_key_id: str | None  # SSEKMSKeyId da resposta
    checksum_sha256: str | None  # ChecksumSHA256 da resposta


@dataclass(frozen=True)
class UrlAssinada:
    """URL pré-assinada de download (R3.2). É uma credencial de 5 minutos: fica fora do `repr`,
    para não ir parar num log por acidente, e nunca entra na auditoria (design § Segurança)."""

    url: str = field(repr=False)
    expira_em: datetime


def conferir_gravacao(esperada: GravacaoEsperada, gravado: ObjetoGravado) -> list[str]:
    """R2.8: lista vazia se confere; senão, os campos que não conferem."""
    problemas = []
    if gravado.sse != esperada.sse:
        problemas.append("sse")
    if esperada.kms_key_id is not None and gravado.kms_key_id != esperada.kms_key_id:
        problemas.append("kms_key_id")
    if gravado.checksum_sha256 != esperada.sha256_b64:
        problemas.append("checksum_sha256")
    return problemas


def chave_do_objeto(*, criado_em: datetime, tipo: str, pedido_id: uuid.UUID, formato: str) -> str:
    """R2.4: `reports/{aaaa}/{mm}/{tipo}/{id}.{formato}`, com o mês do pedido em UTC e sem dado
    pessoal no nome."""
    if criado_em.tzinfo is None:
        raise ValueError("informe o instante do pedido com fuso horário")
    if not _TIPO_DE_RELATORIO.fullmatch(tipo) or formato not in _TIPOS_DE_CONTEUDO:
        raise ValueError("tipo ou formato de relatório fora do padrão")
    utc = criado_em.astimezone(UTC)
    return f"reports/{utc:%Y}/{utc:%m}/{tipo}/{pedido_id}.{formato}"


def nome_do_arquivo(*, tipo: str, data: date, formato: str) -> str:
    """Nome do arquivo baixado: `sgs-{tipo}-{aaaa-mm-dd}.{formato}`, sem dado pessoal (design
    § Adaptador S3)."""
    if not _TIPO_DE_RELATORIO.fullmatch(tipo) or formato not in _TIPOS_DE_CONTEUDO:
        raise ValueError("tipo ou formato de relatório fora do padrão")
    return f"sgs-{tipo}-{data:%Y-%m-%d}.{formato}"


def tipo_de_conteudo(formato: str) -> str:
    """`Content-Type` de cada formato da R1.2."""
    try:
        return _TIPOS_DE_CONTEUDO[formato]
    except KeyError:
        raise ValueError("formato de relatório desconhecido") from None


class ArmazenamentoDeObjetos(Protocol):
    """`sessao` é o id do usuário que vai no `RoleSessionName` (`sgs-{id}`, R2.1)."""

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
        """R2.1 a R2.4, R2.7: envia com SSE e checksum e devolve o que o armazenamento informou."""
        ...

    async def remover(self, key: str, version_id: str | None, *, sessao: str) -> None:
        """R2.8: remove a versão gravada, sem deixar um *delete marker* na frente dela."""
        ...

    async def url_de_download(self, key: str, *, nome: str, sessao: str) -> UrlAssinada:
        """R3.2, R3.6: URL de 5 minutos no endereço público, com o arquivo como anexo."""
        ...
