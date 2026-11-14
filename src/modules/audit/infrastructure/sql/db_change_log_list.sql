-- Objetivo: listar os registros do log do banco, do mais recente para o mais antigo, com filtros
--   por período, tabela e origem, paginados.
-- Justificativa: o log do banco é onde o próprio PostgreSQL registra cada inclusão, alteração e
--   exclusão de unidade, equipamento e serviço, inclusive as feitas fora da API (011/R7.1,
--   R7.2). O Auditor o consulta para achar o que a trilha da aplicação não viu (011/R7.7).
--   - Filtros opcionais, que se somam; o que não vier chega nulo e não restringe. O período
--     inclui as duas pontas e, por ser na chave de partição, deixa o PostgreSQL ler só os meses
--     pedidos. `fora_da_api` verdadeiro traz só `via_api = false`; falso, só `via_api = true`.
--     Os valores entram só como parâmetros, com `CAST` para o asyncpg saber o tipo mesmo
--     quando vêm nulos (ADR-0009).
--   - Sem fragmento de escopo: o log é do banco inteiro, e a rota só chega aqui com
--     `auditoria:read` em escopo global (011/R7.8).
--   - `ORDER BY occurred_at DESC, id DESC`: a ordem da tela; o `id` desempata registros da mesma
--     hora e deixa a paginação estável.
--   - `count(*) OVER ()` dá o total da consulta na mesma passada, para a paginação.
-- Uso: SqlLogDoBanco.listar, na rota GET /api/v1/auditoria/banco (011/T15). O
--   `ix_db_change_log_occurred_at` (011/T7) entrega as linhas na ordem da resposta.
-- Requisitos: 011/R7.7
SELECT
    l.id,
    l.occurred_at,
    l.table_name,
    l.operation,
    l.row_id,
    l.changed_columns,
    l.db_user,
    l.via_api,
    count(*) OVER () AS total
FROM db_change_log AS l
WHERE (CAST(:occurred_from AS timestamptz) IS NULL
       OR l.occurred_at >= CAST(:occurred_from AS timestamptz))
  AND (CAST(:occurred_to AS timestamptz) IS NULL
       OR l.occurred_at <= CAST(:occurred_to AS timestamptz))
  AND (CAST(:table_name AS text) IS NULL
       OR l.table_name = CAST(:table_name AS text))
  AND (CAST(:outside_api AS boolean) IS NULL
       OR l.via_api = NOT CAST(:outside_api AS boolean))
ORDER BY l.occurred_at DESC, l.id DESC
LIMIT :limit OFFSET :offset;
