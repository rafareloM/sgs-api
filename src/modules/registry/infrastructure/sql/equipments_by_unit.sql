-- Objetivo: listar os equipamentos de uma unidade de saúde.
-- Justificativa: a unidade pode ter mais de um equipamento (Policlínica e Maternidade, no modelo
--   do cliente); a rota da unidade os lista para quem lê a unidade. Pelo id (UUID v7, ordem de
--   cadastro).
-- Uso: SqlRepositorioDeEquipamentos.da_unidade, na listagem de equipamentos da unidade (006/T7).
-- Requisitos: 006/R5.1
SELECT
    id, unit_id, name, cnes, equipment_type_code, quantity, status, created_at, updated_at
FROM equipments
WHERE unit_id = :unit_id
ORDER BY id
