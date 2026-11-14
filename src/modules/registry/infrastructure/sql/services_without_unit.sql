-- Objetivo: listar os serviços soltos, que não pertencem a unidade nenhuma (Sala de Vacinação
--   do Shopping).
-- Justificativa: o serviço solto só aparece para o Gestor de Dados, na rota própria
--   (006/R6.2). Pelo id (UUID v7, ordem de cadastro).
-- Uso: SqlRepositorioDeServicos.soltos, na listagem de serviços soltos (006/T8).
-- Requisitos: 006/R6.2, 006/R6.3
SELECT
    id, unit_id, service_type_id, equipment_id, name, in_cnes, status, created_at, updated_at
FROM services
WHERE unit_id IS NULL
ORDER BY id
