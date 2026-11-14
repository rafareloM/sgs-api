-- Objetivo: tirar de PUBLIC o EXECUTE da função de trigger `trg_roles_protect_system()`.
-- Justificativa: privilégio mínimo (011/R10.1). A função é da 0003, anterior aos default
--   privileges da 0011_03, e nasceu com EXECUTE para PUBLIC. O trigger que a usa continua
--   protegendo os papéis de sistema (003/R1.3), porque o PostgreSQL não confere EXECUTE da
--   função de trigger para quem dispara o trigger. Achado da 011/T3, resolvido na revisão do
--   /implement-spec.
-- Uso: privilégios de `trg_roles_protect_system()`; conferido em
--   tests/integration/db/test_privilegios.py.
-- Requisitos: 011/R10.1, 003/R1.3
REVOKE EXECUTE ON FUNCTION trg_roles_protect_system() FROM PUBLIC;
