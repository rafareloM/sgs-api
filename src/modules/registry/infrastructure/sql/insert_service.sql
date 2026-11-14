-- Objetivo: gravar um serviço novo, de uma unidade ou solto, e devolvê-lo como ficou.
-- Justificativa: `unit_id` nulo é o serviço solto (006/R6.2); unidade e equipamento vão pelo
--   id, nunca pelo nome (006/R6.4). O id vem da aplicação (UUID v7); as datas, do banco. O tipo
--   e o equipamento já foram conferidos pelo caso de uso.
-- Uso: SqlRepositorioDeServicos.inserir, nos casos de uso de adicionar serviço (006/T8).
-- Requisitos: 006/R6.1, 006/R6.2, 006/R6.3, 006/R6.4
INSERT INTO services (id, unit_id, service_type_id, equipment_id, name, in_cnes, status)
VALUES (:id, :unit_id, :service_type_id, :equipment_id, :name, :in_cnes, :status)
RETURNING
    id, unit_id, service_type_id, equipment_id, name, in_cnes, status, created_at, updated_at
