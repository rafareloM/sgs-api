-- Objetivo: tirar de PUBLIC o EXECUTE que o PostgreSQL dá a toda função nova.
-- Justificativa: privilégio mínimo (011/R10.1). Ninguém precisa chamar a função de trigger
--   diretamente: o PostgreSQL só confere o EXECUTE de quem cria o trigger, não de quem faz o
--   UPDATE que o dispara, então a aplicação (`sgs_app`) não recebe GRANT e a versão continua
--   sendo incrementada nas escritas dela (conferido pelo login da API em
--   tests/integration/registry/test_versao_trigger.py).
-- Uso: privilégios de `trg_health_units_version`.
-- Requisitos: 011/R10.1
REVOKE EXECUTE ON FUNCTION trg_health_units_version() FROM PUBLIC;
