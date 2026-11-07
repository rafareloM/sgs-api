-- Objetivo: índice GIN de trigramas sobre o nome normalizado, para a busca por trecho do nome.
-- Justificativa: a busca por texto livre acha o termo em qualquer parte do nome, sem acento nem
--   caixa (006/R2.2), e precisa responder em menos de 3 s com 1.000 unidades (006/R2.7). O
--   `ILIKE '%termo%'` não usa B-tree; com `gin_trgm_ops` (extensão `pg_trgm`) usa este índice.
--   Fica sobre a coluna gerada, então a busca e a unicidade usam a mesma normalização (011/R5.2).
-- Uso: busca da 006 (`name_normalized ILIKE '%' || fn_normalize_name(:q) || '%'`, com
--   `similarity` para ordenar).
-- Requisitos: 006/R2.2, 006/R2.7, 011/R5.2
CREATE INDEX ix_health_units_name_normalized_trgm
    ON health_units USING gin (name_normalized gin_trgm_ops);
