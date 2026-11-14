"""registry: procedimento de desativação da unidade (spec 011, T6; R6.1).

`sp_deactivate_unit(p_unit_id, OUT o_previous_status, OUT o_version)` trava a unidade, desativa
se ainda não estiver inativa e devolve o status anterior e a versão nova (incrementada pelo
`trg_health_units_version` da 0011_05); unidade inexistente levanta o SQLSTATE `SGS01`. Sem
COMMIT: roda na transação de quem chama. EXECUTE só para `sgs_app` (011/R10.1). Todo o DDL está
em `migrations/sql/0011_06/`, uma instrução por arquivo, com o cabeçalho que explica cada objeto
(ADR-0009, 011/R11.1).

Revision ID: 0011_06
Revises: 0011_03
Create Date: 2026-11-07
"""

from collections.abc import Sequence

from alembic import op

from migrations.sql_loader import executar_sql

revision: str = "0011_06"
down_revision: str | Sequence[str] | None = "0011_03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REVISAO = "0011_06"

# O procedimento, o REVOKE logo depois de criá-lo e o GRANT a quem o chama (011/R10.1).
ARQUIVOS = (
    "01_sp_deactivate_unit.sql",
    "02_sp_deactivate_unit_revoke_public.sql",
    "03_sp_deactivate_unit_grant_sgs_app.sql",
)


def upgrade() -> None:
    for arquivo in ARQUIVOS:
        executar_sql(REVISAO, arquivo)


def downgrade() -> None:
    op.execute("DROP PROCEDURE sp_deactivate_unit(IN uuid, OUT text, OUT integer)")
