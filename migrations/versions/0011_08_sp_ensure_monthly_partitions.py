"""audit: procedimento das partições mensais do log do banco (spec 011, T8; R6.5 a R6.7).

`sp_ensure_monthly_partitions(p_table, p_months_ahead)` percorre com um cursor os meses do atual
até N meses à frente e cria a partição de cada mês que falta em `db_change_log`, sem apagar
nenhuma; se a DEFAULT já tem registro de um mês, avisa e pula esse mês (design da 011 § Na 0011,
itens 10 e 13). A migração chama o procedimento com 12 meses, e o comando
`sgs-admin banco particoes [--meses N]` o chama depois (011/R6.8). Todo o DDL está em
`migrations/sql/0011_08/`, uma instrução por arquivo, com o cabeçalho que explica cada objeto
(ADR-0009, 011/R11.1).

Revision ID: 0011_08
Revises: 0011_07
Create Date: 2026-11-07
"""

from collections.abc import Sequence

from alembic import op

from migrations.sql_loader import executar_sql

revision: str = "0011_08"
down_revision: str | Sequence[str] | None = "0011_07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REVISAO = "0011_08"

# Criados com o papel `sgs_owner`, como o log da 0011_07 (011/R10.2): o procedimento SECURITY
# DEFINER roda com o privilégio do dono do log, e as partições que ele cria nascem dele.
DO_SGS_OWNER = (
    "01_sp_ensure_monthly_partitions.sql",
    "02_sp_ensure_monthly_partitions_revoke_public.sql",
)

# Executado por quem migra, como no comando administrativo (011/R6.7, R6.8).
DE_QUEM_MIGRA = ("03_call_sp_ensure_monthly_partitions.sql",)


def upgrade() -> None:
    # SET LOCAL vale até o fim da transação das migrações; o RESET devolve o papel de quem migra
    # para o CALL e para as revisões que vierem depois desta.
    op.execute("SET LOCAL ROLE sgs_owner")
    for arquivo in DO_SGS_OWNER:
        executar_sql(REVISAO, arquivo)
    op.execute("RESET ROLE")
    for arquivo in DE_QUEM_MIGRA:
        executar_sql(REVISAO, arquivo)


def downgrade() -> None:
    # Só o procedimento sai. As partições mensais ficam: guardam registros do log, que é só de
    # inclusão, e são apagadas com a tabela-mãe no downgrade da 0011_07.
    op.execute("DROP PROCEDURE sp_ensure_monthly_partitions(regclass, integer)")
