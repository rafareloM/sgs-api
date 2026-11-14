-- Objetivo: dar a área técnica de uma unidade de saúde gravada.
-- Justificativa: distrito, tipo e CNES só se alteram com `unidade:update` de escopo global ou na
--   área técnica da unidade (006/R3.4, design § Campos estruturais). A área sai do tipo da
--   unidade, como no resolvedor de escopo da 003; aqui o tipo conta mesmo desativado, porque a
--   unidade continua nele. A busca usa a chave primária.
-- Uso: SqlRepositorioDeUnidades.area_da_unidade, no caso de uso de atualizar unidade (006/T5).
-- Requisitos: 006/R3.4
SELECT unit_types.technical_area_id
FROM health_units
JOIN unit_types ON unit_types.id = health_units.unit_type_id
WHERE health_units.id = :id
