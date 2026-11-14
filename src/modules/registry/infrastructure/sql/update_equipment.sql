-- Objetivo: gravar os dados de negócio de um equipamento e devolvê-lo como ficou.
-- Justificativa: todas as colunas de negócio vão no SET, com o valor novo ou o que já tinham,
--   num texto fixo, sem montar SQL por campo enviado (ADR-0009); o caso de uso só chega aqui se
--   algum valor mudou. `equipments` não tem trigger de data, então `updated_at` é posto aqui. A
--   unidade (`unit_id`) não muda por esta rota.
-- Uso: SqlRepositorioDeEquipamentos.atualizar, no caso de uso de alterar equipamento (006/T7).
-- Requisitos: 006/R5.1
UPDATE equipments
SET
    name = :name,
    cnes = :cnes,
    equipment_type_code = :equipment_type_code,
    quantity = :quantity,
    status = :status,
    updated_at = now()
WHERE id = :id
RETURNING
    id, unit_id, name, cnes, equipment_type_code, quantity, status, created_at, updated_at
