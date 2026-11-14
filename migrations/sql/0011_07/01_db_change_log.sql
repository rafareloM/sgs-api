-- Objetivo: criar o log do banco, onde o próprio PostgreSQL registra cada inclusão, alteração e
--   exclusão de unidade, equipamento e serviço, venha de onde vier.
-- Justificativa: a trilha de auditoria (`audit_log`) só vê o que passa pela API; uma alteração
--   feita direto no banco (superusuário, script, outra ferramenta) não deixaria rastro. O log
--   do banco fecha essa lacuna para o Auditor (011/R7.1, R7.2). Tabela separada, e não o
--   `audit_log`: o hash encadeado da trilha é calculado em Python e quebraria (design da 011
--   § Decisões).
--   - Colunas: data e hora (`occurred_at`, `clock_timestamp()` para cada linha ter a sua hora,
--     mesmo numa transação longa), tabela, operação, identificador da linha, colunas alteradas
--     em JSON (`{coluna: {"de": v, "para": v}}`), usuário de banco, se veio da API e a
--     transação (`txid`, que junta as linhas de uma mesma alteração em cascata) (011/R7.1,
--     R7.5).
--   - CHECK em `table_name` e `operation`: só as três tabelas do cadastro e as três operações.
--   - Particionada por mês em `occurred_at` (RANGE): o log só cresce, e a consulta por período
--     (011/R7.7) lê só os meses pedidos. As partições mensais são criadas pelo procedimento da
--     011/T8; a DEFAULT (próximo arquivo) recebe o que cair fora delas. Por isso a chave
--     primária inclui `occurred_at`: numa tabela particionada, toda chave única contém a chave
--     de partição.
--   - Criada com o papel `sgs_owner` (`SET LOCAL ROLE`, na revisão): ele é o dono, a única
--     escrita é a do trigger que roda com o privilégio dele, e a tabela não recebe os default
--     privileges da 0001, que dariam DML ao `sgs_app` (011/R7.6, R10.2).
-- Uso: `trg_registry_change_log` (grava), rota `GET /auditoria/banco` (011/T15, lê) e
--   `sp_ensure_monthly_partitions` (011/T8, cria as partições).
-- Requisitos: 011/R7.1, 011/R7.2, 011/R7.5, 011/R7.6
CREATE TABLE db_change_log (
    id bigint GENERATED ALWAYS AS IDENTITY,
    occurred_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    table_name text NOT NULL,
    operation text NOT NULL,
    row_id uuid NOT NULL,
    changed_columns jsonb NOT NULL,
    db_user text NOT NULL,
    via_api boolean NOT NULL,
    txid bigint NOT NULL,
    CONSTRAINT pk_db_change_log PRIMARY KEY (id, occurred_at),
    CONSTRAINT ck_db_change_log_table_name_valido
        CHECK (table_name IN ('health_units', 'equipments', 'services')),
    CONSTRAINT ck_db_change_log_operation_valido
        CHECK (operation IN ('INSERT', 'UPDATE', 'DELETE'))
) PARTITION BY RANGE (occurred_at);
