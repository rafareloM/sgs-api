"""identity: `users.authz_version`, a versão das atribuições de cada usuário (spec 003, T3; R4.5).

O cache de permissões efetivas (design da 003 § Resolução de permissões, passo 3) guarda a versão
com que resolveu as permissões e a confere a cada requisição. Quem altera as atribuições de um
usuário incrementa a versão na mesma transação, e a mudança vale na próxima requisição.

Revision ID: 0003_1
Revises: 0003
Create Date: 2026-11-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_1"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("authz_version", sa.Integer, nullable=False, server_default=sa.text("0")),
    )


def downgrade() -> None:
    op.drop_column("users", "authz_version")
