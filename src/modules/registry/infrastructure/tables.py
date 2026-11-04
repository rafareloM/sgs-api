"""Tabelas de cadastro (unidade_saude, equipamento) compatíveis com a migração 0002."""

from sqlalchemy import (
    CHAR,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    String,
    Table,
    text,
)

from src.core.db import metadata

unidade_saude = Table(
    "unidade_saude",
    metadata,
    Column("idunidade", Integer, Identity(always=True), primary_key=True),
    Column("codigocnes", String(7), nullable=False, unique=True),
    Column("nome", String(150), nullable=False),
    Column("tipo", String(50), nullable=False),
    Column("endereco", String(200), nullable=False),
    Column("cep", CHAR(8), nullable=False),
    Column("distritosanitario", String(50), nullable=False),
    Column("telefone", String(15), nullable=True),
    Column("status", String(20), nullable=False),
    Column("datacriacao", DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    Column("dataatualizacao", DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint("codigocnes ~ '^[0-9]{7}$'", name="ck_unidade_saude_codigocnes_formato"),
    CheckConstraint("btrim(nome) <> ''", name="ck_unidade_saude_nome_nao_vazio"),
    CheckConstraint(
        "tipo IN ('UBS', 'UPA', 'Hospital', 'Laboratório', 'Posto de Saúde', 'Centro de Saúde')",
        name="ck_unidade_saude_tipo_valido",
    ),
    CheckConstraint("btrim(endereco) <> ''", name="ck_unidade_saude_endereco_nao_vazio"),
    CheckConstraint("cep ~ '^[0-9]{8}$'", name="ck_unidade_saude_cep_formato"),
    CheckConstraint(
        "btrim(distritosanitario) <> ''",
        name="ck_unidade_saude_distritosanitario_nao_vazio",
    ),
    CheckConstraint(
        "telefone IS NULL OR telefone ~ '^\\(?[0-9]{2,3}\\)?[[:space:]]?[0-9]{4,5}-?[0-9]{4}$'",
        name="ck_unidade_saude_telefone_formato",
    ),
    CheckConstraint(
        "status IN ('Ativa', 'Inativa', 'Em reforma', 'Suspensa')",
        name="ck_unidade_saude_status_valido",
    ),
    CheckConstraint("dataatualizacao >= datacriacao", name="ck_unidade_saude_datas_consistentes"),
)

equipamento = Table(
    "equipamento",
    metadata,
    Column("idequipamento", Integer, Identity(always=True), primary_key=True),
    Column("nome", String(100), nullable=False),
    Column("tipo", String(50), nullable=False),
    Column("quantidade", Integer, nullable=False),
    Column(
        "idunidade",
        Integer,
        ForeignKey(
            "unidade_saude.idunidade",
            onupdate="CASCADE",
            name="fk_equipamento_idunidade_unidade_saude",
        ),
        nullable=False,
    ),
    CheckConstraint("btrim(nome) <> ''", name="ck_equipamento_nome_nao_vazio"),
    CheckConstraint(
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
    CheckConstraint(
        "quantidade >= 0 AND quantidade <= 5000",
        name="ck_equipamento_quantidade_faixa",
    ),
)
