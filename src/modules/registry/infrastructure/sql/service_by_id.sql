-- Objetivo: ler um serviço inteiro pelo id.
-- Justificativa: a alteração e a remoção conferem que o serviço é da unidade da rota e usam os
--   valores de antes no diff da auditoria. Busca pela chave primária.
-- Uso: SqlRepositorioDeServicos.ler, nos casos de uso de alterar e remover serviço (006/T8).
-- Requisitos: 006/R6.1
SELECT
    id, unit_id, service_type_id, equipment_id, name, in_cnes, status, created_at, updated_at
FROM services
WHERE id = :id
