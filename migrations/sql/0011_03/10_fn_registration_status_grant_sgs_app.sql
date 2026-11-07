-- Objetivo: deixar a aplicação (`sgs_app`) executar `fn_registration_status`.
-- Justificativa: o inventário e os relatórios chamam a função pelo login da API, e a
--   `vw_unit_inventory` usa `security_invoker`, então a função roda com o privilégio de quem
--   consulta (011/R4.6). Só o `sgs_app` precisa dela (011/R10.1).
-- Uso: privilégios de `fn_registration_status`.
-- Requisitos: 011/R5.3, 011/R10.1
GRANT EXECUTE ON FUNCTION fn_registration_status(health_units) TO sgs_app;
