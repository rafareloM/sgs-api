-- Objetivo: gravar um equipamento novo, de uma unidade ou sem unidade, e devolvê-lo como ficou.
-- Justificativa: `unit_id` nulo é o equipamento sem unidade (006/R5.2). O id vem da aplicação
--   (UUID v7); as datas, do banco. O tipo já foi conferido ativo pelo caso de uso.
-- Uso: SqlRepositorioDeEquipamentos.inserir, nos casos de uso de adicionar equipamento (006/T7).
-- Requisitos: 006/R5.1, 006/R5.2
INSERT INTO equipments (id, unit_id, name, cnes, equipment_type_code, quantity, status)
VALUES (:id, :unit_id, :name, :cnes, :equipment_type_code, :quantity, :status)
RETURNING
    id, unit_id, name, cnes, equipment_type_code, quantity, status, created_at, updated_at
