-- Objetivo: contar os equipamentos de um tipo de equipamento, pelo código do tipo.
-- Justificativa: corrigir o código de um tipo leva o código novo aos equipamentos dele (FK com ON
--   UPDATE CASCADE), e a auditoria da correção registra quantos foram afetados (011/R9.2). Roda
--   depois do UPDATE, na mesma transação, com o código novo.
-- Uso: SqlRepositorioDeReferencias.equipamentos_do_tipo, na correção de código (011/T18).
-- Requisitos: 006/R7.3, 011/R9.2
SELECT count(*)
FROM equipments
WHERE equipment_type_code = :code
