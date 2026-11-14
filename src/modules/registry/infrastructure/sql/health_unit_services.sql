-- Objetivo: listar os serviços vinculados a uma unidade de saúde.
-- Justificativa: o detalhe da unidade traz os serviços dela (006/R2.5), pelo id da unidade, nunca
--   pelo nome (006/R6.4); o serviço solto (006/R6.2) não aparece. Usa `ix_services_unit_id`
--   (0011_03). Ordem pelo nome, com o id para desempatar.
-- Uso: SqlRepositorioDeUnidades.detalhar, rota GET /api/v1/unidades/{id} (006/T4).
-- Requisitos: 006/R2.5, 006/R6.4
SELECT id, name, service_type_id, equipment_id, in_cnes, status
FROM services
WHERE unit_id = :unit_id
ORDER BY name, id;
