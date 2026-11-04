"""Suporte ao CRUD e ao dashboard da Etapa 03 no schema legado em português.

Revision ID: 0003
Revises: 0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent")
    op.alter_column("unidade_saude", "codigocnes", nullable=True)
    op.drop_constraint("ck_unidade_saude_codigocnes_formato", "unidade_saude", type_="check")
    op.create_check_constraint(
        "ck_unidade_saude_codigocnes_formato",
        "unidade_saude",
        "codigocnes IS NULL OR codigocnes ~ '^[0-9]{7}$'",
    )
    op.add_column(
        "unidade_saude",
        sa.Column("cnes_pendente", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column("unidade_saude", sa.Column("versao", sa.Integer(), server_default="1"))
    op.add_column("unidade_saude", sa.Column("nomenormalizado", sa.String(length=150)))
    op.execute(
        "UPDATE unidade_saude SET nomenormalizado = "
        "regexp_replace(unaccent(lower(nome)), '\\s+', ' ', 'g')"
    )
    op.execute("UPDATE unidade_saude SET cnes_pendente = codigocnes IS NULL")
    op.alter_column("unidade_saude", "nomenormalizado", nullable=False)
    op.alter_column("unidade_saude", "versao", nullable=False)
    op.create_check_constraint("ck_unidade_saude_versao_positiva", "unidade_saude", "versao > 0")
    op.create_unique_constraint(
        "uq_unidade_saude_distrito_nome_normalizado",
        "unidade_saude",
        ["distritosanitario", "nomenormalizado"],
    )
    op.add_column("alteracao", sa.Column("motivo", sa.String(length=255), nullable=True))
    op.alter_column("equipamento", "idunidade", nullable=True)
    op.execute(
        """
        CREATE FUNCTION normalizar_unidade_saude_etapa3() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            NEW.nomenormalizado := regexp_replace(unaccent(lower(NEW.nome)), '\\s+', ' ', 'g');
            NEW.cnes_pendente := NEW.codigocnes IS NULL;
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER unidade_saude_normalizar_etapa3 "
        "BEFORE INSERT OR UPDATE OF nome, codigocnes ON unidade_saude "
        "FOR EACH ROW EXECUTE FUNCTION normalizar_unidade_saude_etapa3()"
    )


def downgrade() -> None:
    op.alter_column("equipamento", "idunidade", nullable=False)
    op.execute("DROP TRIGGER unidade_saude_normalizar_etapa3 ON unidade_saude")
    op.execute("DROP FUNCTION normalizar_unidade_saude_etapa3()")
    op.drop_column("alteracao", "motivo")
    op.drop_constraint("uq_unidade_saude_distrito_nome_normalizado", "unidade_saude")
    op.drop_constraint("ck_unidade_saude_versao_positiva", "unidade_saude")
    op.drop_column("unidade_saude", "nomenormalizado")
    op.drop_column("unidade_saude", "versao")
    op.drop_column("unidade_saude", "cnes_pendente")
    op.drop_constraint("ck_unidade_saude_codigocnes_formato", "unidade_saude", type_="check")
    op.create_check_constraint(
        "ck_unidade_saude_codigocnes_formato",
        "unidade_saude",
        "codigocnes ~ '^[0-9]{7}$'",
    )
    op.alter_column("unidade_saude", "codigocnes", nullable=False)
