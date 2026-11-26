"""Publicação das chaves públicas de verificação dos relatórios (spec 005, R5.4 e R5.5)."""

from src.modules.reports.domain.assinatura import AssinadorDeRelatorio, PublicJwk

# Reexportados para a camada api, que só importa a application (steering/structure.md).
__all__ = ["AssinadorDeRelatorio", "PublicJwk", "chaves_publicas"]


def chaves_publicas(assinador: AssinadorDeRelatorio | None) -> tuple[PublicJwk, ...]:
    """A chave ativa e as anteriores: um relatório assinado antes de uma rotação continua
    verificável (R5.5). Sem chave configurada, nada é assinado e não há o que publicar."""
    return () if assinador is None else assinador.chaves_publicas()
