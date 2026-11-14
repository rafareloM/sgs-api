-- Objetivo: dar a área técnica de um tipo de unidade ativo.
-- Justificativa: quem cadastra precisa de `unidade:create` no escopo da área técnica do tipo
--   informado (006/R1.1); a unidade ainda não existe, então a área sai do tipo, como o
--   resolvedor de escopo da 003 faz com uma unidade gravada. Tipo desativado (exclusão lógica,
--   decisão U5 da 011) não recebe unidade nova e conta como inexistente.
-- Uso: SqlRepositorioDeUnidades.area_do_tipo, no caso de uso de criar unidade (006/T3).
-- Requisitos: 006/R1.1, 006/R1.2
SELECT technical_area_id
FROM unit_types
WHERE id = :unit_type_id
  AND is_active
