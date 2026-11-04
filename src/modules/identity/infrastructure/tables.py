"""Tabelas de identidade (perfil, usuario) compatíveis com a migração 0002."""

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    ForeignKey,
    Identity,
    Integer,
    String,
    Table,
    text,
)

from src.core.db import metadata

perfil = Table(
    "perfil",
    metadata,
    Column("idperfil", Integer, Identity(always=True), primary_key=True),
    Column("nomeperfil", String(50), nullable=False, unique=True),
    Column("permissoes", String(255), nullable=False),
    CheckConstraint("btrim(nomeperfil) <> ''", name="ck_perfil_nomeperfil_nao_vazio"),
    CheckConstraint("btrim(permissoes) <> ''", name="ck_perfil_permissoes_nao_vazio"),
)

usuario = Table(
    "usuario",
    metadata,
    Column("idusuario", Integer, Identity(always=True), primary_key=True),
    Column("nome", String(100), nullable=False),
    Column("email", String(100), nullable=False, unique=True),
    Column("senhahash", String(255), nullable=False),
    Column("doisfatorhabilitado", Boolean, nullable=False, server_default=text("false")),
    Column("doisfatorsegredo", String(255), nullable=True),
    Column(
        "idperfil",
        Integer,
        ForeignKey("perfil.idperfil", onupdate="CASCADE", name="fk_usuario_idperfil_perfil"),
        nullable=False,
    ),
    Column(
        "idunidade",
        Integer,
        ForeignKey(
            "unidade_saude.idunidade",
            onupdate="CASCADE",
            ondelete="SET NULL",
            name="fk_usuario_idunidade_unidade_saude",
        ),
        nullable=True,
    ),
    CheckConstraint("btrim(nome) <> ''", name="ck_usuario_nome_nao_vazio"),
    CheckConstraint(
        "email ~* '^[A-Za-z0-9._%+\\-]+@[A-Za-z0-9.\\-]+\\.[A-Za-z]{2,}$'",
        name="ck_usuario_email_formato",
    ),
    CheckConstraint("length(senhahash) >= 60", name="ck_usuario_senhahash_tamanho"),
    CheckConstraint(
        "(doisfatorhabilitado = false) OR "
        "(doisfatorsegredo IS NOT NULL AND btrim(doisfatorsegredo) <> '')",
        name="ck_usuario_doisfator_consistente",
    ),
)
