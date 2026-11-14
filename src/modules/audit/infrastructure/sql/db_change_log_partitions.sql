-- Objetivo: listar as partições do log do banco, cada uma com o intervalo de datas e a
--   quantidade de registros.
-- Justificativa: o Auditor confere se a manutenção mensal criou os meses à frente e se algum
--   registro caiu na DEFAULT, sinal de manutenção atrasada (011/R6.9; design § Riscos).
--   - As partições vêm do catálogo: `pg_inherits` liga a tabela-mãe às filhas e
--     `pg_get_expr(relpartbound)` dá os limites (`FOR VALUES FROM ('…') TO ('…')`). Os limites
--     saem com o fuso da sessão escrito no texto, então o `CAST` para `timestamptz` não depende
--     dele. A DEFAULT não tem limites: `de` e `ate` nulos.
--   - A contagem lê a tabela-mãe agrupando por `tableoid` (a partição de cada linha): o
--     `sgs_app` só tem SELECT na mãe, não nas partições (011/R7.6). O `LEFT JOIN` mantém a
--     partição vazia, com zero.
--   - Ordem: os meses do mais antigo para o mais novo e a DEFAULT por último.
-- Uso: SqlLogDoBanco.particoes, na rota GET /api/v1/auditoria/banco/particoes (011/T15).
-- Requisitos: 011/R6.9
WITH particoes AS (
    SELECT
        c.oid,
        c.relname,
        pg_get_expr(c.relpartbound, c.oid) AS limites
    FROM pg_inherits AS i
    JOIN pg_class AS c ON c.oid = i.inhrelid
    WHERE i.inhparent = CAST('db_change_log' AS regclass)
),
contagem AS (
    SELECT l.tableoid, count(*) AS registros
    FROM db_change_log AS l
    GROUP BY l.tableoid
)
SELECT
    p.relname AS name,
    CAST(substring(p.limites FROM 'FROM \(''([^'']+)''\)') AS timestamptz) AS range_from,
    CAST(substring(p.limites FROM 'TO \(''([^'']+)''\)') AS timestamptz) AS range_to,
    coalesce(n.registros, 0) AS row_count
FROM particoes AS p
LEFT JOIN contagem AS n ON n.tableoid = p.oid
ORDER BY range_from ASC NULLS LAST, p.relname;
