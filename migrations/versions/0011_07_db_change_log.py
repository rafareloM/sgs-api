"""audit: log do banco e trigger de log do cadastro (spec 011, T7; R7.1 a R7.6).

O próprio PostgreSQL registra em `db_change_log` cada inclusão, alteração e exclusão de unidade,
equipamento e serviço, inclusive as feitas fora da API (design da 011 § Na 0011, itens 9, 11 e
13). Todo o DDL está em `migrations/sql/0011_07/`, uma instrução por arquivo, com o cabeçalho que
explica cada objeto (ADR-0009, 011/R11.1):

- `db_change_log`, particionada por mês, com a partição DEFAULT, o índice por data e só SELECT
  para o `sgs_app` (011/R7.1, R7.6);
- `trg_registry_change_log()`, SECURITY DEFINER, sem EXECUTE para PUBLIC (011/R7.1 a R7.5,
  R10.1);
- um trigger AFTER por linha em `health_units`, `equipments` e `services`.

Revision ID: 0011_07
Revises: 0011_04
Create Date: 2026-11-07
"""

from collections.abc import Sequence

from alembic import op

from migrations.sql_loader import executar_sql

revision: str = "0011_07"
down_revision: str | Sequence[str] | None = "0011_04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REVISAO = "0011_07"

# Criados com o papel `sgs_owner`, para nascerem com ele como dono (011/R10.2): a tabela e a
# partição ficam fora dos default privileges da 0001 (que dariam DML ao `sgs_app`), e a função
# SECURITY DEFINER roda com o privilégio dele, não com o de quem migra.
DO_SGS_OWNER = (
    "01_db_change_log.sql",
    "02_db_change_log_default.sql",
    "03_ix_db_change_log_occurred_at.sql",
    "04_db_change_log_grant_sgs_app.sql",
    "05_fn_trg_registry_change_log.sql",
    "06_fn_trg_registry_change_log_revoke_public.sql",
)

# Criados por quem migra: o `sgs_owner` só lê as tabelas do cadastro e não pode pôr trigger nelas.
DE_QUEM_MIGRA = (
    "07_trg_registry_change_log_health_units.sql",
    "08_trg_registry_change_log_equipments.sql",
    "09_trg_registry_change_log_services.sql",
)


def upgrade() -> None:
    # SET LOCAL vale até o fim da transação das migrações; o RESET devolve o papel de quem migra
    # para os arquivos seguintes e para as revisões que vierem depois desta.
    op.execute("SET LOCAL ROLE sgs_owner")
    for arquivo in DO_SGS_OWNER:
        executar_sql(REVISAO, arquivo)
    op.execute("RESET ROLE")
    for arquivo in DE_QUEM_MIGRA:
        executar_sql(REVISAO, arquivo)


def downgrade() -> None:
    # Na ordem inversa. Apagar a tabela-mãe apaga as partições e o índice delas.
    op.execute("DROP TRIGGER trg_registry_change_log ON services")
    op.execute("DROP TRIGGER trg_registry_change_log ON equipments")
    op.execute("DROP TRIGGER trg_registry_change_log ON health_units")
    op.execute("DROP FUNCTION trg_registry_change_log()")
    op.execute("DROP TABLE db_change_log")
