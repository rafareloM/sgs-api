"""db: tira de PUBLIC o EXECUTE das funções de trigger anteriores à 0011 (spec 011; R10.1).

`audit_log_somente_insercao()` (0001) e `trg_roles_protect_system()` (0003) nasceram antes dos
default privileges da 0011_03, com o EXECUTE que o PostgreSQL dá a PUBLIC. Os triggers seguem
funcionando: quem dispara um trigger não precisa de EXECUTE na função dele. Achado da 011/T3,
resolvido na revisão do /implement-spec. O DDL está em `migrations/sql/0011_09/`, uma instrução
por arquivo (ADR-0009, 011/R11.1).

Revision ID: 0011_09
Revises: 0011_08
Create Date: 2026-11-14
"""

from collections.abc import Sequence

from alembic import op

from migrations.sql_loader import executar_sql

revision: str = "0011_09"
down_revision: str | Sequence[str] | None = "0011_08"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REVISAO = "0011_09"

ARQUIVOS = (
    "01_audit_log_somente_insercao_revoke_public.sql",
    "02_trg_roles_protect_system_revoke_public.sql",
)


def upgrade() -> None:
    for arquivo in ARQUIVOS:
        executar_sql(REVISAO, arquivo)


def downgrade() -> None:
    op.execute("GRANT EXECUTE ON FUNCTION trg_roles_protect_system() TO PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION audit_log_somente_insercao() TO PUBLIC")
