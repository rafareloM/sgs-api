-- Objetivo: deixar a aplicação (`sgs_app`) executar `sp_deactivate_unit`.
-- Justificativa: o caso de uso de desativação da 006 chama o procedimento pelo login da API
--   (011/R6.2); `sgs_app` é um dos dois papéis com EXECUTE em objetos da 0011, ao lado de
--   `fn_registration_status` (design da 011 § 0011, item 13; § Segurança).
-- Uso: privilégios de `sp_deactivate_unit`.
-- Requisitos: 011/R6.2, 011/R10.1
GRANT EXECUTE ON PROCEDURE sp_deactivate_unit(IN uuid, OUT text, OUT integer) TO sgs_app;
