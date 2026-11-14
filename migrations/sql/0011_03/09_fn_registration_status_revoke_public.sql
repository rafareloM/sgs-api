-- Objetivo: garantir que PUBLIC não executa `fn_registration_status`.
-- Justificativa: privilégio mínimo (011/R10.1). O default privilege de
--   04_default_privileges_migration_owner.sql já faz a função nascer sem EXECUTE para PUBLIC; o
--   REVOKE explícito (design da 011, item 13) deixa a regra visível junto da função e vale mesmo
--   se a migração rodar com outro papel.
-- Uso: privilégios de `fn_registration_status`.
-- Requisitos: 011/R10.1
REVOKE EXECUTE ON FUNCTION fn_registration_status(health_units) FROM PUBLIC;
