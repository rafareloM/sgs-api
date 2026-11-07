"""banco: views do inventário e do histórico das unidades (spec 011, T4).

Itens 6 e 7 do design da 011 § Na 0011. Todo o DDL do upgrade está em `migrations/sql/0011_04/`,
uma instrução por arquivo, com o cabeçalho que explica cada objeto (ADR-0009, 011/R11.1):

- `vw_unit_inventory`: por unidade, tipo, área técnica, distrito, status, situação cadastral e
  as quantidades de equipamentos, serviços e serviços fora do CNES, sem dado pessoal (011/R4.1,
  R4.2);
- `vw_unit_history`: eventos da trilha de cada unidade, inclusive os de equipamentos e serviços,
  com autor, distrito, tipo e a lista {campo, de, para} (011/R4.4);
- as duas com `security_invoker = true`, para respeitarem as permissões de quem consulta, e só
  com SELECT para o `sgs_app` (011/R4.6).

Revision ID: 0011_04
Revises: 0011_06
Create Date: 2026-11-07
"""

from collections.abc import Sequence

from alembic import op

from migrations.sql_loader import executar_sql

revision: str = "0011_04"
down_revision: str | Sequence[str] | None = "0011_06"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REVISAO = "0011_04"

ARQUIVOS = (
    "01_vw_unit_inventory.sql",
    "02_vw_unit_history.sql",
    "03_views_revoke_dml_sgs_app.sql",
)


def upgrade() -> None:
    for arquivo in ARQUIVOS:
        executar_sql(REVISAO, arquivo)


def downgrade() -> None:
    op.execute("DROP VIEW vw_unit_history")
    op.execute("DROP VIEW vw_unit_inventory")
