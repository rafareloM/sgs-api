"""Armazenamento S3 falso dos testes dos relatórios (005/T5 e T6)."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, BinaryIO

from src.modules.reports.domain.armazenamento import ObjetoGravado, UrlAssinada

SEGREDO_DO_SDK = "https://s3.interno/reports/x?X-Amz-Signature=segredo"
URL_ASSINADA = "https://s3.localhost/sgs-relatorios/reports/x?X-Amz-Signature=assinatura"


@dataclass
class ArmazenamentoFalso:
    """Guarda o que recebe e responde como um S3 que aplica a SSE e confere o checksum, ou com
    o que o teste trocar em `resposta`."""

    sse: str | None = "AES256"
    checksum: str | None = None  # None: devolve o checksum recebido
    falhar_no_envio: bool = False
    enviados: list[dict[str, Any]] = field(default_factory=list)
    removidos: list[tuple[str, str | None, str]] = field(default_factory=list)
    urls: list[tuple[str, str, str]] = field(default_factory=list)

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
        if self.falhar_no_envio:
            raise RuntimeError(SEGREDO_DO_SDK)
        self.enviados.append(
            {
                "key": key,
                "conteudo": arquivo.read(),
                "content_type": content_type,
                "sha256_b64": sha256_b64,
                "metadados": dict(metadados),
                "sessao": sessao,
            }
        )
        return ObjetoGravado(
            key=key,
            version_id=f"v-{len(self.enviados)}",
            sse=self.sse,
            kms_key_id=None,
            checksum_sha256=self.checksum or sha256_b64,
        )

    async def remover(self, key: str, version_id: str | None, *, sessao: str) -> None:
        self.removidos.append((key, version_id, sessao))

    async def url_de_download(self, key: str, *, nome: str, sessao: str) -> UrlAssinada:
        self.urls.append((key, nome, sessao))
        return UrlAssinada(url=URL_ASSINADA, expira_em=datetime.now(UTC) + timedelta(minutes=5))
