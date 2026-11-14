-- Objetivo: apagar um equipamento.
-- Justificativa: equipamento sai do cadastro por exclusão física (decisão U5 da 011). Os
--   serviços que estavam nele continuam na unidade, sem equipamento, pela FK
--   `services.equipment_id` com ON DELETE SET NULL (011/R9.1); o log do banco registra as duas
--   alterações (011/R7.5).
-- Uso: SqlRepositorioDeEquipamentos.remover, no caso de uso de remover equipamento (006/T7).
-- Requisitos: 006/R5.1, 011/R9.1
DELETE FROM equipments
WHERE id = :id
RETURNING id
