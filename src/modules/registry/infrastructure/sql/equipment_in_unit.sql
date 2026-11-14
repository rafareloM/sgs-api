-- Objetivo: dizer se um equipamento existe e é de uma unidade (ou, com unidade nula, se é sem
--   unidade).
-- Justificativa: o serviço pode estar num equipamento, apontado pelo id (006/R6.4), e o
--   equipamento tem de ser da mesma unidade do serviço; o serviço solto (006/R6.2) só entra em
--   equipamento sem unidade, como a UTI móvel. `IS NOT DISTINCT FROM` compara também o nulo,
--   num texto só para os dois casos. Busca pela chave primária.
-- Uso: SqlRepositorioDeServicos.equipamento_na_unidade, nos casos de uso de serviço (006/T8).
-- Requisitos: 006/R6.1, 006/R6.2
SELECT EXISTS (
    SELECT 1
    FROM equipments
    WHERE id = :equipment_id
      AND unit_id IS NOT DISTINCT FROM CAST(:unit_id AS uuid)
)
