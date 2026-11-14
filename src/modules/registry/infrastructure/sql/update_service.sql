-- Objetivo: gravar os dados de negócio de um serviço e devolvê-lo como ficou.
-- Justificativa: todas as colunas de negócio vão no SET, com o valor novo ou o que já tinham,
--   num texto fixo, sem montar SQL por campo enviado (ADR-0009); o caso de uso só chega aqui se
--   algum valor mudou. `services` não tem trigger de data, então `updated_at` é posto aqui. A
--   unidade (`unit_id`) não muda por esta rota.
-- Uso: SqlRepositorioDeServicos.atualizar, no caso de uso de alterar serviço (006/T8).
-- Requisitos: 006/R6.1, 006/R6.3
UPDATE services
SET
    service_type_id = :service_type_id,
    equipment_id = :equipment_id,
    name = :name,
    in_cnes = :in_cnes,
    status = :status,
    updated_at = now()
WHERE id = :id
RETURNING
    id, unit_id, service_type_id, equipment_id, name, in_cnes, status, created_at, updated_at
