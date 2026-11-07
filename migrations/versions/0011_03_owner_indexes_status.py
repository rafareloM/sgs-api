"""banco: papel dono, privilégios, índices e situação cadastral (spec 011, T3).

Papel e privilégios da 0011 (design da 011 § Na 0011, itens 1 a 5, e o item 13 para a função desta
revisão). Todo o DDL do upgrade está em `migrations/sql/0011_03/`, uma instrução por arquivo, com
o cabeçalho que explica cada objeto (ADR-0009, 011/R11.1):

- papel `sgs_owner` (sem login, sem superusuário), com o schema e só o SELECT que as funções do
  dono leem (011/R10.2);
- default privileges: rotina nova do dono do banco ou do `sgs_owner` nasce sem EXECUTE para
  PUBLIC (011/R10.1);
- índices `ix_audit_log_entity` (histórico da unidade) e `ix_services_unit_id` (serviços da
  unidade) (011/R1.1, R1.2);
- `fn_registration_status`, a situação cadastral, com EXECUTE só para o `sgs_app` (011/R5.3,
  R10.1).

Revision ID: 0011_03
Revises: 0011_05
Create Date: 2026-11-07
"""

from collections.abc import Sequence

from alembic import op

from migrations.sql_loader import executar_sql

revision: str = "0011_03"
down_revision: str | Sequence[str] | None = "0011_05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REVISAO = "0011_03"

# Ordem do design: o papel e os privilégios antes dos objetos, para tudo o que vier depois (nesta
# revisão e nas próximas da 0011) já nascer sem EXECUTE para PUBLIC.
ARQUIVOS = (
    "01_sgs_owner.sql",
    "02_sgs_owner_schema.sql",
    "03_sgs_owner_select.sql",
    "04_default_privileges_migration_owner.sql",
    "05_default_privileges_sgs_owner.sql",
    "06_ix_audit_log_entity.sql",
    "07_ix_services_unit_id.sql",
    "08_fn_registration_status.sql",
    "09_fn_registration_status_revoke_public.sql",
    "10_fn_registration_status_grant_sgs_app.sql",
)


def upgrade() -> None:
    for arquivo in ARQUIVOS:
        executar_sql(REVISAO, arquivo)


def downgrade() -> None:
    # Na ordem inversa. Devolver o EXECUTE a PUBLIC nos default privileges volta ao padrão do
    # PostgreSQL (a entrada some do catálogo).
    op.execute("DROP FUNCTION fn_registration_status(health_units)")
    op.execute("DROP INDEX ix_services_unit_id")
    op.execute("DROP INDEX ix_audit_log_entity")
    op.execute("ALTER DEFAULT PRIVILEGES FOR ROLE sgs_owner GRANT EXECUTE ON FUNCTIONS TO PUBLIC")
    op.execute(
        "ALTER DEFAULT PRIVILEGES FOR ROLE CURRENT_USER GRANT EXECUTE ON FUNCTIONS TO PUBLIC"
    )
    op.execute(
        "REVOKE SELECT ON health_units, equipments, services, users, audit_log, districts,"
        " unit_types, technical_areas FROM sgs_owner"
    )
    op.execute("REVOKE USAGE, CREATE ON SCHEMA public FROM sgs_owner")
    # O `sgs_owner` fica, como o `sgs_app` na 0001: papéis valem para o servidor inteiro e podem
    # ter objetos e privilégios em outros bancos.
