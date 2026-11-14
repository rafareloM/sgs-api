-- Objetivo: listar os serviços de uma unidade de saúde.
-- Justificativa: a rota da unidade lista os serviços dela para quem lê a unidade (006/R6.1),
--   pelo id da unidade, nunca pelo nome (006/R6.4): renomear a unidade não muda a lista. Usa
--   `ix_services_unit_id` (0011_03). Pelo id (UUID v7, ordem de cadastro), como os equipamentos.
-- Uso: SqlRepositorioDeServicos.da_unidade, na listagem de serviços da unidade (006/T8).
-- Requisitos: 006/R6.1, 006/R6.3, 006/R6.4
SELECT
    id, unit_id, service_type_id, equipment_id, name, in_cnes, status, created_at, updated_at
FROM services
WHERE unit_id = :unit_id
ORDER BY id
