"""Tabelas do cadastro (spec 006), para o Alembic e para o teste `test_migracoes_sincronizadas`.

A 0003_access (spec 003) criou os distritos, as áreas técnicas e um stub de `health_units` para o
escopo do RBAC; a 0006_registry completa essas tabelas e cria as demais. O DDL de verdade está em
`migrations/sql/0006/` (ADR-0009): aqui fica só o espelho dele, e os repositórios do `registry`
escrevem o SQL à mão com `text()`.

Os ids das referências vêm de uma sequência (`smallserial`), como a 0003 criou os de distritos e
áreas técnicas.
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Table,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

from src.core.db import metadata


def _timestamps() -> tuple[Column[datetime], Column[datetime]]:
    return (
        Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
        Column(
            "updated_at",
            DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
            onupdate=func.now(),
        ),
    )


def _ativo() -> Column[bool]:
    """Exclusão lógica das referências (006/R7.2; decisão U5 da 011)."""
    return Column("is_active", Boolean, nullable=False, server_default=text("true"))


districts = Table(
    "districts",
    metadata,
    Column("id", SmallInteger, primary_key=True),
    Column("code", String(20), nullable=False, unique=True),
    Column("name", String(100), nullable=False),
    _ativo(),
    *_timestamps(),
)

technical_areas = Table(
    "technical_areas",
    metadata,
    Column("id", SmallInteger, primary_key=True),
    Column("code", String(50), nullable=False, unique=True),
    Column("name", String(100), nullable=False),
    _ativo(),
    *_timestamps(),
)

unit_types = Table(
    "unit_types",
    metadata,
    Column("id", SmallInteger, primary_key=True),
    Column("code", String(50), nullable=False, unique=True),
    Column("name", String(100), nullable=False),
    Column("technical_area_id", SmallInteger, ForeignKey("technical_areas.id"), nullable=False),
    _ativo(),
    *_timestamps(),
)

equipment_types = Table(
    "equipment_types",
    metadata,
    Column("id", SmallInteger, primary_key=True),
    # Único: `equipments.equipment_type_code` aponta para ele com ON UPDATE CASCADE (011/R9.2).
    Column("code", String(50), nullable=False, unique=True),
    Column("name", String(100), nullable=False),
    _ativo(),
    *_timestamps(),
)

service_types = Table(
    "service_types",
    metadata,
    Column("id", SmallInteger, primary_key=True),
    Column("code", String(50), nullable=False, unique=True),
    Column("name", String(100), nullable=False),
    _ativo(),
    *_timestamps(),
)

STATUS_DA_UNIDADE = ("ativa", "inativa", "em_implantacao")

health_units = Table(
    "health_units",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("district_id", SmallInteger, ForeignKey("districts.id"), nullable=False),
    Column("unit_type_id", SmallInteger, ForeignKey("unit_types.id"), nullable=False),
    Column("cnes", String(7), nullable=True),
    Column("name", String(200), nullable=False),
    # Gerada pela `fn_normalize_name` (011/R5); a aplicação lê, nunca grava.
    Column(
        "name_normalized",
        Text,
        Computed("fn_normalize_name(name::text)", persisted=True),
        nullable=False,
    ),
    Column("manager_name", String(150), nullable=True),  # dado pessoal (LGPD)
    Column("cep", String(8), nullable=False),
    Column("address", String(200), nullable=False),
    Column("neighborhood", String(100), nullable=True),
    Column("phone", String(20), nullable=True),
    Column("opening_hours", JSONB, nullable=True),
    Column("latitude", Numeric(9, 6), nullable=True),
    Column("longitude", Numeric(9, 6), nullable=True),
    Column("status", String(20), nullable=False),
    Column("pending_issues", Integer, nullable=False, server_default=text("0")),
    Column("version", Integer, nullable=False, server_default=text("1")),
    *_timestamps(),
    CheckConstraint(f"status IN {STATUS_DA_UNIDADE}", name="status_valido"),
    CheckConstraint("pending_issues >= 0", name="pending_issues_nao_negativo"),
    Index(
        "ix_health_units_cnes",
        "cnes",
        unique=True,
        postgresql_where=text("cnes IS NOT NULL"),
    ),
    Index(
        "ix_health_units_district_id_name_normalized", "district_id", "name_normalized", unique=True
    ),
    Index(
        "ix_health_units_name_normalized_trgm",
        "name_normalized",
        postgresql_using="gin",
        postgresql_ops={"name_normalized": "gin_trgm_ops"},
    ),
)

equipments = Table(
    "equipments",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("unit_id", Uuid, ForeignKey("health_units.id", ondelete="RESTRICT"), nullable=True),
    Column("cnes", String(7), nullable=True),
    Column("name", String(200), nullable=False),
    Column(
        "equipment_type_code",
        String(50),
        ForeignKey("equipment_types.code", onupdate="CASCADE"),
        nullable=False,
    ),
    Column("quantity", Integer, nullable=False, server_default=text("1")),
    Column("status", String(20), nullable=False),
    *_timestamps(),
)

services = Table(
    "services",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("service_type_id", SmallInteger, ForeignKey("service_types.id"), nullable=False),
    Column("unit_id", Uuid, ForeignKey("health_units.id", ondelete="RESTRICT"), nullable=True),
    Column("equipment_id", Uuid, ForeignKey("equipments.id", ondelete="SET NULL"), nullable=True),
    Column("name", String(200), nullable=False),
    Column("in_cnes", Boolean, nullable=False, server_default=text("false")),
    Column("status", String(20), nullable=False),
    *_timestamps(),
    # Serviços de uma unidade (migração 0011_03, spec 011 R1.2).
    Index("ix_services_unit_id", "unit_id"),
)
