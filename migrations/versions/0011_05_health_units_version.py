"""registry: versão da unidade incrementada pelo banco (spec 011, T5; R8.1, R8.2).

`trg_health_units_version` (BEFORE UPDATE, por linha) soma 1 a `health_units.version` e atualiza
`updated_at` sempre que um dado da unidade muda, venha a escrita da API, de procedimento ou de
fora da aplicação; mudança só em `pending_issues` não conta (design da 011 § 0011, item 12). Todo
o DDL está em `migrations/sql/0011_05/`, uma instrução por arquivo, com o cabeçalho que explica
cada objeto (ADR-0009, 011/R11.1).

Revision ID: 0011_05
Revises: 0006
Create Date: 2026-11-07
"""

from collections.abc import Sequence

from alembic import op

from migrations.sql_loader import executar_sql

revision: str = "0011_05"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REVISAO = "0011_05"

# A função antes do trigger que a chama; o REVOKE logo depois de criá-la (011/R10.1).
ARQUIVOS = (
    "01_fn_trg_health_units_version.sql",
    "02_fn_trg_health_units_version_revoke_public.sql",
    "03_trg_health_units_version.sql",
)


def upgrade() -> None:
    for arquivo in ARQUIVOS:
        executar_sql(REVISAO, arquivo)


def downgrade() -> None:
    op.execute("DROP TRIGGER trg_health_units_version ON health_units")
    op.execute("DROP FUNCTION trg_health_units_version()")
