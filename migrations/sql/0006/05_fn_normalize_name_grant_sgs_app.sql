-- Objetivo: deixar a aplicação (`sgs_app`) executar `fn_normalize_name`.
-- Justificativa: a busca da 006 chama a função, e a coluna gerada `health_units.name_normalized`
--   a avalia com o privilégio de quem insere ou altera a unidade: sem o EXECUTE, o INSERT pelo
--   login da API falha com "permission denied for function fn_normalize_name" (risco do design
--   da 011, conferido em tests/integration/registry/test_normalizacao.py).
-- Uso: privilégios de `fn_normalize_name`.
-- Requisitos: 011/R5.2, 011/R10.1
GRANT EXECUTE ON FUNCTION fn_normalize_name(text) TO sgs_app;
