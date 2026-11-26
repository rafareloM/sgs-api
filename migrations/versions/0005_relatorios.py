"""reports: pedidos de exportação de relatório (spec 005, T1).

Cria `report_jobs` conforme o design da 005 § Modelo de dados, com a versão do objeto, as
colunas de assinatura, o `CHECK` de coerência do `concluido` e os índices da listagem e dos
pedidos abertos. O DDL está em `migrations/sql/0005/`, uma instrução por arquivo, com cabeçalho
(ADR-0009).

`down_revision` aponta para a `0004_diretorio` (004/T1), que entrou antes: quem integra por
último aponta para a outra (`specs/004-diretorio-ldap-oidc/tasks.md` § Frentes), e
`uv run alembic heads` mostra uma cabeça só.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-25
"""

from collections.abc import Sequence

from alembic import op

from migrations.sql_loader import executar_sql

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REVISAO = "0005"

ARQUIVOS = (
    "01_report_jobs.sql",
    "02_ix_report_jobs_requested_by_created_at.sql",
    "03_ix_report_jobs_status_aberto.sql",
)


def upgrade() -> None:
    for arquivo in ARQUIVOS:
        executar_sql(REVISAO, arquivo)


def downgrade() -> None:
    # Os índices e as restrições saem com a tabela.
    op.execute("DROP TABLE report_jobs")
