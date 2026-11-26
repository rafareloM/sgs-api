"""Tabela de pedidos de relatório, igual à da migração 0005_relatorios (spec 005, T1)."""

from sqlalchemy import (
    CHAR,
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    Table,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

from src.core.db import metadata
from src.modules.reports.domain.pedidos import (
    ERRO_MAX,
    FormatoDeRelatorio,
    StatusDoPedido,
    TipoDeRelatorio,
)


def _lista(valores: type[TipoDeRelatorio | FormatoDeRelatorio | StatusDoPedido]) -> str:
    return "(" + ", ".join(f"'{v.value}'" for v in valores) + ")"


report_jobs = Table(
    "report_jobs",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("report_type", Text, nullable=False),
    Column("format", Text, nullable=False),
    Column("filters", JSONB, nullable=False),
    Column("requested_by", Uuid, ForeignKey("users.id"), nullable=False),
    Column("scope_snapshot", JSONB, nullable=False),
    Column("status", Text, nullable=False),
    Column("storage_bucket", Text, nullable=True),
    Column("storage_key", Text, nullable=True),
    Column("storage_version_id", Text, nullable=True),
    Column("size_bytes", BigInteger, nullable=True),
    Column("sha256", CHAR(64), nullable=True),
    Column("signature", Text, nullable=True),
    Column("signature_alg", Text, nullable=True),
    Column("signature_kid", Text, nullable=True),
    Column("error", String(ERRO_MAX), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column(
        "updated_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    ),
    Column("started_at", DateTime(timezone=True), nullable=True),
    Column("finished_at", DateTime(timezone=True), nullable=True),
    Column("expires_at", DateTime(timezone=True), nullable=True),
    CheckConstraint(f"report_type IN {_lista(TipoDeRelatorio)}", name="tipo_valido"),
    CheckConstraint(f"format IN {_lista(FormatoDeRelatorio)}", name="formato_valido"),
    CheckConstraint(f"status IN {_lista(StatusDoPedido)}", name="status_valido"),
    CheckConstraint(
        "status <> 'concluido' OR (storage_key IS NOT NULL AND sha256 IS NOT NULL"
        " AND signature IS NOT NULL AND signature_alg IS NOT NULL"
        " AND signature_kid IS NOT NULL)",
        name="concluido_completo",
    ),
    CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="sha256_hex"),
)

# Listagem por solicitante, mais recente primeiro (R3.5).
Index(
    "ix_report_jobs_requested_by_created_at",
    report_jobs.c.requested_by,
    report_jobs.c.created_at.desc(),
)

# Pedidos abertos: os marcados como interrompidos na subida (design § Geração e envio, passo 8).
Index(
    "ix_report_jobs_status_aberto",
    report_jobs.c.status,
    postgresql_where=text("status IN ('pendente', 'gerando')"),
)
