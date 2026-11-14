-- Objetivo: gravar os dados de negócio de uma unidade de saúde, só se ela ainda está na versão
--   que o usuário tem em mãos, e devolvê-la como ficou no banco.
-- Justificativa:
--   - `version = :expected_version` no WHERE é a checagem otimista do `If-Match` (006/R3.2):
--     se outra escrita, pela API ou fora dela, passou na frente, o trigger
--     `trg_health_units_version` já incrementou a versão e nenhuma linha volta (412; 011/R8.3).
--     Em READ COMMITTED, uma escrita concorrente na mesma linha faz este UPDATE esperar e
--     reavaliar o WHERE com a versão nova, então nenhuma alteração é sobrescrita;
--   - a aplicação nunca mexe em `version` nem em `updated_at`: o trigger da 011 (R8.1) os mantém,
--     e o RETURNING já traz a versão nova para o `ETag`;
--   - todas as colunas de negócio vão no SET, com o valor novo ou o que já tinham: o trigger só
--     incrementa a versão se algum valor mudou, e o caso de uso nem chega aqui sem mudança
--     (006/R3.6). Um texto fixo, sem montar SQL por campo enviado (ADR-0009);
--   - `name_normalized` não entra: é gerada pela `fn_normalize_name` (011/R5.2). Os índices
--     únicos do CNES e do nome no distrito recusam repetição (006/R1.3, R1.4); o repositório roda
--     este UPDATE num savepoint e traduz o `unique_violation` em 409.
-- Uso: SqlRepositorioDeUnidades.atualizar, no caso de uso de atualizar unidade (006/T5, 011/T17).
-- Requisitos: 006/R3.1, 006/R3.2, 011/R8.3
UPDATE health_units
SET
    name = :name,
    cnes = :cnes,
    unit_type_id = :unit_type_id,
    district_id = :district_id,
    cep = :cep,
    address = :address,
    neighborhood = :neighborhood,
    phone = :phone,
    manager_name = :manager_name,
    opening_hours = :opening_hours,
    latitude = :latitude,
    longitude = :longitude,
    status = :status
WHERE id = :id
  AND version = :expected_version
RETURNING
    id, name, cnes, unit_type_id, district_id, cep, address, neighborhood, phone,
    manager_name, opening_hours, latitude, longitude, status,
    pending_issues, version, created_at, updated_at
