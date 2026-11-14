-- Objetivo: listar os equipamentos vinculados a uma unidade de saúde.
-- Justificativa: o detalhe da unidade traz os equipamentos dela (006/R2.5); o vínculo é pela FK
--   `equipments.unit_id`, então o equipamento sem unidade (006/R5.2) não aparece. Ordem pelo nome,
--   com o id para desempatar.
-- Uso: SqlRepositorioDeUnidades.detalhar, rota GET /api/v1/unidades/{id} (006/T4).
-- Requisitos: 006/R2.5
SELECT id, name, cnes, equipment_type_code, quantity, status
FROM equipments
WHERE unit_id = :unit_id
ORDER BY name, id;
