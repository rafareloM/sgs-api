"""Etapa 02: criacao das tabelas perfil, unidade_saude, usuario, equipamento e alteracao.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. PERFIL
    op.create_table(
        "perfil",
        sa.Column("idperfil", sa.Integer(), sa.Identity(always=True), nullable=False),
        sa.Column("nomeperfil", sa.String(length=50), nullable=False),
        sa.Column("permissoes", sa.String(length=255), nullable=False),
        sa.PrimaryKeyConstraint("idperfil", name="pk_perfil"),
        sa.UniqueConstraint("nomeperfil", name="uq_perfil_nomeperfil"),
        sa.CheckConstraint("btrim(nomeperfil) <> ''", name="ck_perfil_nomeperfil_nao_vazio"),
        sa.CheckConstraint("btrim(permissoes) <> ''", name="ck_perfil_permissoes_nao_vazio"),
    )

    # 2. UNIDADE_SAUDE
    op.create_table(
        "unidade_saude",
        sa.Column("idunidade", sa.Integer(), sa.Identity(always=True), nullable=False),
        sa.Column("codigocnes", sa.String(length=7), nullable=False),
        sa.Column("nome", sa.String(length=150), nullable=False),
        sa.Column("tipo", sa.String(length=50), nullable=False),
        sa.Column("endereco", sa.String(length=200), nullable=False),
        sa.Column("cep", sa.CHAR(length=8), nullable=False),
        sa.Column("distritosanitario", sa.String(length=50), nullable=False),
        sa.Column("telefone", sa.String(length=15), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "datacriacao",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "dataatualizacao",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("idunidade", name="pk_unidade_saude"),
        sa.UniqueConstraint("codigocnes", name="uq_unidade_saude_codigocnes"),
        sa.CheckConstraint(
            "codigocnes ~ '^[0-9]{7}$'",
            name="ck_unidade_saude_codigocnes_formato",
        ),
        sa.CheckConstraint("btrim(nome) <> ''", name="ck_unidade_saude_nome_nao_vazio"),
        sa.CheckConstraint(
            "tipo IN ("
            "'UBS', 'UPA', 'Hospital', 'Laboratório', 'Posto de Saúde', 'Centro de Saúde'"
            ")",
            name="ck_unidade_saude_tipo_valido",
        ),
        sa.CheckConstraint("btrim(endereco) <> ''", name="ck_unidade_saude_endereco_nao_vazio"),
        sa.CheckConstraint("cep ~ '^[0-9]{8}$'", name="ck_unidade_saude_cep_formato"),
        sa.CheckConstraint(
            "btrim(distritosanitario) <> ''",
            name="ck_unidade_saude_distritosanitario_nao_vazio",
        ),
        sa.CheckConstraint(
            "telefone IS NULL OR telefone ~ '^\\(?[0-9]{2,3}\\)?[[:space:]]?[0-9]{4,5}-?[0-9]{4}$'",
            name="ck_unidade_saude_telefone_formato",
        ),
        sa.CheckConstraint(
            "status IN ('Ativa', 'Inativa', 'Em reforma', 'Suspensa')",
            name="ck_unidade_saude_status_valido",
        ),
        sa.CheckConstraint(
            "dataatualizacao >= datacriacao",
            name="ck_unidade_saude_datas_consistentes",
        ),
    )

    # 3. USUARIO
    op.create_table(
        "usuario",
        sa.Column("idusuario", sa.Integer(), sa.Identity(always=True), nullable=False),
        sa.Column("nome", sa.String(length=100), nullable=False),
        sa.Column("email", sa.String(length=100), nullable=False),
        sa.Column("senhahash", sa.String(length=255), nullable=False),
        sa.Column(
            "doisfatorhabilitado",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("doisfatorsegredo", sa.String(length=255), nullable=True),
        sa.Column("idperfil", sa.Integer(), nullable=False),
        sa.Column("idunidade", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("idusuario", name="pk_usuario"),
        sa.UniqueConstraint("email", name="uq_usuario_email"),
        sa.CheckConstraint("btrim(nome) <> ''", name="ck_usuario_nome_nao_vazio"),
        sa.CheckConstraint(
            "email ~* '^[A-Za-z0-9._%+\\-]+@[A-Za-z0-9.\\-]+\\.[A-Za-z]{2,}$'",
            name="ck_usuario_email_formato",
        ),
        sa.CheckConstraint("length(senhahash) >= 60", name="ck_usuario_senhahash_tamanho"),
        sa.CheckConstraint(
            "(doisfatorhabilitado = false) OR "
            "(doisfatorsegredo IS NOT NULL AND btrim(doisfatorsegredo) <> '')",
            name="ck_usuario_doisfator_consistente",
        ),
        sa.ForeignKeyConstraint(
            ["idperfil"],
            ["perfil.idperfil"],
            name="fk_usuario_idperfil_perfil",
            onupdate="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["idunidade"],
            ["unidade_saude.idunidade"],
            name="fk_usuario_idunidade_unidade_saude",
            onupdate="CASCADE",
            ondelete="SET NULL",
        ),
    )

    # 4. EQUIPAMENTO
    op.create_table(
        "equipamento",
        sa.Column("idequipamento", sa.Integer(), sa.Identity(always=True), nullable=False),
        sa.Column("nome", sa.String(length=100), nullable=False),
        sa.Column("tipo", sa.String(length=50), nullable=False),
        sa.Column("quantidade", sa.Integer(), nullable=False),
        sa.Column("idunidade", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("idequipamento", name="pk_equipamento"),
        sa.CheckConstraint("btrim(nome) <> ''", name="ck_equipamento_nome_nao_vazio"),
        sa.CheckConstraint(
            "tipo IN ("
            "'Monitor de sinais vitais', "
            "'Respirador', "
            "'Tomógrafo', "
            "'Ultrassom', "
            "'Balança', "
            "'Aparelho de RX', "
            "'Cadeira de rodas', "
            "'Desfibrilador', "
            "'Fitas de esterilização', "
            "'Estetoscópio'"
            ")",
            name="ck_equipamento_tipo_valido",
        ),
        sa.CheckConstraint(
            "quantidade >= 0 AND quantidade <= 5000",
            name="ck_equipamento_quantidade_faixa",
        ),
        sa.ForeignKeyConstraint(
            ["idunidade"],
            ["unidade_saude.idunidade"],
            name="fk_equipamento_idunidade_unidade_saude",
            onupdate="CASCADE",
        ),
    )

    # 5. ALTERACAO
    op.create_table(
        "alteracao",
        sa.Column("idalteracao", sa.Integer(), sa.Identity(always=True), nullable=False),
        sa.Column(
            "datahora",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("campoalterado", sa.String(length=50), nullable=False),
        sa.Column("valoranterior", sa.String(length=255), nullable=True),
        sa.Column("valornovo", sa.String(length=255), nullable=True),
        sa.Column("idunidade", sa.Integer(), nullable=False),
        sa.Column("idusuario", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("idalteracao", name="pk_alteracao"),
        sa.CheckConstraint(
            "btrim(campoalterado) <> ''",
            name="ck_alteracao_campoalterado_nao_vazio",
        ),
        sa.CheckConstraint(
            "valoranterior IS NOT NULL OR valornovo IS NOT NULL",
            name="ck_alteracao_valores_nao_ambos_nulos",
        ),
        sa.ForeignKeyConstraint(
            ["idunidade"],
            ["unidade_saude.idunidade"],
            name="fk_alteracao_idunidade_unidade_saude",
            onupdate="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["idusuario"],
            ["usuario.idusuario"],
            name="fk_alteracao_idusuario_usuario",
            onupdate="CASCADE",
        ),
    )


def downgrade() -> None:
    op.drop_table("alteracao")
    op.drop_table("equipamento")
    op.drop_table("usuario")
    op.drop_table("unidade_saude")
    op.drop_table("perfil")
