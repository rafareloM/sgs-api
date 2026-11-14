-- Objetivo: apagar um serviço.
-- Justificativa: serviço sai do cadastro por exclusão física (decisão U5 da 011), como o
--   equipamento; a trilha guarda os campos que ele tinha (`unidade.servico_removido`) e o log do
--   banco registra a remoção (011/R7.5).
-- Uso: SqlRepositorioDeServicos.remover, no caso de uso de remover serviço (006/T8).
-- Requisitos: 006/R6.1
DELETE FROM services
WHERE id = :id
RETURNING id
