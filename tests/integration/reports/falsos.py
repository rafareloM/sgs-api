"""Armazenamento S3 falso dos testes dos relatórios (005/T5 e T6) e a geração montada com ele."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, BinaryIO

import anyio.to_thread

from src.modules.reports.api.relatorios import transacoes_dos_relatorios
from src.modules.reports.application.gerar import Destino, Geracao
from src.modules.reports.domain.armazenamento import ObjetoGravado, UrlAssinada
from src.modules.reports.infrastructure.assinatura import Es256AssinadorDeRelatorio
from src.modules.reports.infrastructure.consultas import SqlConsultasDeRelatorio
from src.modules.reports.infrastructure.generators import novo_gerador
from tests.factories import make_jwt_private_keys, make_settings

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


def geracao_falsa(estado: Any, armazenamento: "ArmazenamentoFalso | None" = None) -> Geracao:
    """A geração de produção (consultas, geradores, assinador) sobre o `app.state` de um app sem
    S3, com o armazenamento falso no lugar do S3."""
    assinador = Es256AssinadorDeRelatorio.from_settings(
        make_settings(report_signing_keys=make_jwt_private_keys("rel-teste"))
    )
    assert assinador is not None
    return Geracao(
        transacoes=transacoes_dos_relatorios(estado),
        consultas=SqlConsultasDeRelatorio(estado.engine),
        armazenamento=armazenamento or ArmazenamentoFalso(),
        assinador=assinador,
        novo_gerador=novo_gerador,
        em_thread=anyio.to_thread.run_sync,
        destino=Destino(
            bucket="sgs-relatorios", sse="AES256", kms_key_id=None, retencao=timedelta(days=90)
        ),
        agora=lambda: datetime.now(UTC),
    )
