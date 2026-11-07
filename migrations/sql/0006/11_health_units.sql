-- Objetivo: completar a unidade de saúde, que a 0003 (spec 003) criou só com id, distrito e tipo,
--   com as colunas de docs/architecture/modelo-dados.md § 2.
-- Justificativa:
--   - nome, tipo, distrito, endereço com CEP e status são obrigatórios (006/R1.2); o CNES não,
--     porque há serviços municipais fora do CNES (006/R1.5). CNES com 7 e CEP com 8 caracteres
--     (só dígitos); o formato é conferido nos schemas da API (design da 006 § Schemas);
--   - `name_normalized` é gerada pela `fn_normalize_name` (criada antes, em 03): a unicidade por
--     nome (006/R1.4) e a busca (006/R2.2) leem a mesma coluna, calculada pela mesma regra
--     (011/R5.2), sem a aplicação poder gravar outro valor. O `::text` é o tipo do parâmetro da
--     função; o PostgreSQL o escreveria assim de todo jeito;
--   - `status` só aceita os três valores do modelo; desativar é mudar o status, nunca apagar
--     (006/R4.2);
--   - `version` é a versão do ETag/`If-Match` (006/R3.2), incrementada pelo trigger da 011 (R8);
--   - `pending_issues` conta as pendências de validação, mantida pela 007, nunca negativa;
--   - o nome do gestor (`manager_name`) é dado pessoal (LGPD, steering/security.md): fica fora do
--     inventário e mascarado no log do banco (011/R4.2, R7.3).
--   A tabela está vazia (nada escreve no stub da 0003), então as colunas obrigatórias entram sem
--   valor padrão.
-- Uso: casos de uso de unidade da 006 e consultas, views e procedimentos da 011.
-- Requisitos: 006/R1.2, 006/R1.4, 006/R1.5, 006/R3.2, 006/R4.2, 011/R5.2
ALTER TABLE health_units
    ADD COLUMN cnes varchar(7),
    ADD COLUMN name varchar(200) NOT NULL,
    ADD COLUMN name_normalized text NOT NULL
        GENERATED ALWAYS AS (fn_normalize_name(name::text)) STORED,
    ADD COLUMN manager_name varchar(150),
    ADD COLUMN cep varchar(8) NOT NULL,
    ADD COLUMN address varchar(200) NOT NULL,
    ADD COLUMN neighborhood varchar(100),
    ADD COLUMN phone varchar(20),
    ADD COLUMN opening_hours jsonb,
    ADD COLUMN latitude numeric(9, 6),
    ADD COLUMN longitude numeric(9, 6),
    ADD COLUMN status varchar(20) NOT NULL,
    ADD COLUMN pending_issues integer NOT NULL DEFAULT 0,
    ADD COLUMN version integer NOT NULL DEFAULT 1,
    ADD COLUMN created_at timestamptz NOT NULL DEFAULT now(),
    ADD COLUMN updated_at timestamptz NOT NULL DEFAULT now(),
    ADD CONSTRAINT ck_health_units_status_valido
        CHECK (status IN ('ativa', 'inativa', 'em_implantacao')),
    ADD CONSTRAINT ck_health_units_pending_issues_nao_negativo CHECK (pending_issues >= 0);
