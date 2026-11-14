-- Objetivo: listar os equipamentos que não pertencem a unidade nenhuma (UTI móvel do SAMU).
-- Justificativa: o equipamento sem unidade só aparece para o Gestor de Dados, na rota própria
--   (006/R5.2). Pelo id (UUID v7, ordem de cadastro).
-- Uso: SqlRepositorioDeEquipamentos.sem_unidade, na listagem de equipamentos sem unidade
--   (006/T7).
-- Requisitos: 006/R5.2
SELECT
    id, unit_id, name, cnes, equipment_type_code, quantity, status, created_at, updated_at
FROM equipments
WHERE unit_id IS NULL
ORDER BY id
