-- Objetivo: instalar a extensão `pg_trgm` (trigramas), que dá índice GIN a `ILIKE '%...%'` e a
--   função `similarity`.
-- Justificativa: a busca por texto livre procura o termo em qualquer parte do nome (006/R2.2) e
--   precisa responder em menos de 3 s com 1.000 unidades (006/R2.7); um índice B-tree não serve a
--   `ILIKE` com `%` no começo. Extensão confiável (trusted): o dono do banco a instala sem ser
--   superusuário.
-- Uso: `ix_health_units_name_normalized_trgm` e a ordenação por `similarity` da busca da 006.
-- Requisitos: 006/R2.2, 006/R2.7
CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public;
