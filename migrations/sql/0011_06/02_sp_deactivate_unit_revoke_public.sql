-- Objetivo: garantir que PUBLIC não executa `sp_deactivate_unit`.
-- Justificativa: privilégio mínimo (011/R10.1): o procedimento só é executado por quem precisa
--   dele, a aplicação (próximo arquivo). O default privilege da 0011_03
--   (04_default_privileges_migration_owner.sql) já faz o procedimento nascer sem EXECUTE para
--   PUBLIC; o REVOKE explícito (design da 011, item 13) deixa a regra visível junto do
--   procedimento e vale mesmo se a migração rodar com outro papel.
-- Uso: privilégios de `sp_deactivate_unit`.
-- Requisitos: 011/R10.1
REVOKE EXECUTE ON PROCEDURE sp_deactivate_unit(IN uuid, OUT text, OUT integer) FROM PUBLIC;
