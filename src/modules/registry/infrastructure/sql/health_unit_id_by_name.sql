-- Objetivo: achar a unidade do distrito com o mesmo nome normalizado (sem acento, caixa e
--   espaços extras).
-- Justificativa: "Espaço Azul" e "ESPACO  azul" no mesmo distrito são a mesma unidade
--   (006/R1.4). O nome procurado passa pela mesma `fn_normalize_name` que gera a coluna
--   `name_normalized` (011/R5.2), então a regra é uma só; a busca usa o índice único
--   `ix_health_units_district_id_name_normalized`.
-- Uso: SqlRepositorioDeUnidades.com_nome, no caso de uso de criar unidade (006/T3).
-- Requisitos: 006/R1.4, 011/R5.2
SELECT id
FROM health_units
WHERE district_id = :district_id
  AND name_normalized = fn_normalize_name(:name)
