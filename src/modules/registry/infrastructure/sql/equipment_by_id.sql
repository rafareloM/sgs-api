-- Objetivo: ler um equipamento inteiro pelo id.
-- Justificativa: a alteração e a remoção conferem que o equipamento é da unidade da rota e
--   usam os valores de antes no diff da auditoria (006/R5.3). Busca pela chave primária.
-- Uso: SqlRepositorioDeEquipamentos.ler, nos casos de uso de alterar e remover equipamento
--   (006/T7).
-- Requisitos: 006/R5.1, 006/R5.3
SELECT
    id, unit_id, name, cnes, equipment_type_code, quantity, status, created_at, updated_at
FROM equipments
WHERE id = :id
