-- Objetivo: tirar de PUBLIC o EXECUTE que o PostgreSQL dá a toda função nova.
-- Justificativa: privilégio mínimo (011/R10.1): a função só é executada por quem precisa dela, a
--   aplicação (próximo arquivo).
-- Uso: privilégios de `fn_normalize_name`.
-- Requisitos: 011/R10.1
REVOKE EXECUTE ON FUNCTION fn_normalize_name(text) FROM PUBLIC;
