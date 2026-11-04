-- ========================================================
-- Projeto: Plataforma de Governança de Dados de Saúde
-- Secretaria de Saúde do Recife
-- Etapa 02 - Criação de tabelas
-- ========================================================

DROP TABLE IF EXISTS ALTERACAO;
DROP TABLE IF EXISTS EQUIPAMENTO;
DROP TABLE IF EXISTS USUARIO;
DROP TABLE IF EXISTS UNIDADE_SAUDE;
DROP TABLE IF EXISTS PERFIL;

CREATE TABLE PERFIL (
    IdPerfil INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    NomePerfil VARCHAR(50) NOT NULL UNIQUE CHECK (TRIM(NomePerfil) <> ''),
    Permissoes VARCHAR(255) NOT NULL CHECK (TRIM(Permissoes) <> '')
);

CREATE TABLE UNIDADE_SAUDE (
    IdUnidade INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    CodigoCNES VARCHAR(7) NOT NULL UNIQUE CHECK (CodigoCNES ~ '^[0-9]{7}$'),
    Nome VARCHAR(150) NOT NULL CHECK (TRIM(Nome) <> ''),
    Tipo VARCHAR(50) NOT NULL CHECK (Tipo IN ('UBS', 'UPA', 'Hospital', 'Laboratório', 'Posto de Saúde', 'Centro de Saúde')),
    Endereco VARCHAR(200) NOT NULL CHECK (TRIM(Endereco) <> ''),
    CEP CHAR(8) NOT NULL CHECK (CEP ~ '^[0-9]{8}$'),
    DistritoSanitario VARCHAR(50) NOT NULL CHECK (TRIM(DistritoSanitario) <> ''),
    Telefone VARCHAR(15) DEFAULT NULL CHECK (Telefone IS NULL OR Telefone ~ '^\(?[0-9]{2,3}\)?[[:space:]]?[0-9]{4,5}-?[0-9]{4}$'),
    Status VARCHAR(20) NOT NULL CHECK (Status IN ('Ativa', 'Inativa', 'Em reforma', 'Suspensa')),
    DataCriacao TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    DataAtualizacao TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (DataAtualizacao >= DataCriacao)
);

CREATE TABLE USUARIO (
    IdUsuario INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    Nome VARCHAR(100) NOT NULL CHECK (TRIM(Nome) <> ''),
    Email VARCHAR(100) NOT NULL UNIQUE CHECK (Email ~* '^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$'),
    SenhaHash VARCHAR(255) NOT NULL CHECK (LENGTH(SenhaHash) >= 60),
    DoisFatorHabilitado BOOLEAN NOT NULL DEFAULT FALSE,
    DoisFatorSegredo VARCHAR(255) DEFAULT NULL,
    IdPerfil INTEGER NOT NULL,
    IdUnidade INTEGER DEFAULT NULL,
    CONSTRAINT fk_usuario_perfil
        FOREIGN KEY (IdPerfil) REFERENCES PERFIL (IdPerfil)
        ON UPDATE CASCADE,
    CONSTRAINT fk_usuario_unidade
        FOREIGN KEY (IdUnidade) REFERENCES UNIDADE_SAUDE (IdUnidade)
        ON DELETE SET NULL
        ON UPDATE CASCADE,
    CHECK ((DoisFatorHabilitado = FALSE) OR (DoisFatorSegredo IS NOT NULL AND TRIM(DoisFatorSegredo) <> ''))
);

CREATE TABLE EQUIPAMENTO (
    IdEquipamento INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    Nome VARCHAR(100) NOT NULL CHECK (TRIM(Nome) <> ''),
    Tipo VARCHAR(50) NOT NULL CHECK (Tipo IN (
        'Monitor de sinais vitais',
        'Respirador',
        'Tomógrafo',
        'Ultrassom',
        'Balança',
        'Aparelho de RX',
        'Cadeira de rodas',
        'Desfibrilador',
        'Fitas de esterilização',
        'Estetoscópio'
    )),
    Quantidade INTEGER NOT NULL CHECK (Quantidade >= 0 AND Quantidade <= 5000),
    IdUnidade INTEGER NOT NULL,
    CONSTRAINT fk_equipamento_unidade
        FOREIGN KEY (IdUnidade) REFERENCES UNIDADE_SAUDE (IdUnidade)
        ON UPDATE CASCADE
);

CREATE TABLE ALTERACAO (
    IdAlteracao INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    DataHora TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CampoAlterado VARCHAR(50) NOT NULL CHECK (TRIM(CampoAlterado) <> ''),
    ValorAnterior VARCHAR(255) DEFAULT NULL,
    ValorNovo VARCHAR(255) DEFAULT NULL,
    IdUnidade INTEGER NOT NULL,
    IdUsuario INTEGER NOT NULL,
    CONSTRAINT fk_alteracao_unidade
        FOREIGN KEY (IdUnidade) REFERENCES UNIDADE_SAUDE (IdUnidade)
        ON UPDATE CASCADE,
    CONSTRAINT fk_alteracao_usuario
        FOREIGN KEY (IdUsuario) REFERENCES USUARIO (IdUsuario)
        ON UPDATE CASCADE,
    CHECK (ValorAnterior IS NOT NULL OR ValorNovo IS NOT NULL)
);
