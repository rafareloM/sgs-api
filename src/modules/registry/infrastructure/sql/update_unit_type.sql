-- Objetivo: alterar um item de unit_types (tipos de unidade) e devolvê-lo como estava e como ficou.
-- Justificativa:
--   - só os campos enviados mudam: parâmetro nulo mantém o valor (`COALESCE`); a API não deixa
--     enviar nulo nesses campos;
--   - a subconsulta trava a linha (`FOR UPDATE`) e devolve os valores de antes, para o de/para da
--     auditoria (006/R7.2), num comando só; item inexistente não devolve linha (404);
--   - código repetido viola `uq_unit_types_code`, e o caso de uso responde 409.
-- Uso: SqlRepositorioDeReferencias.atualizar, na rota `PATCH /referencias/tipos-unidade/{id}` (006/T9).
-- Requisitos: 006/R7.2
UPDATE unit_types AS item
SET code = COALESCE(:code, item.code),
    name = COALESCE(:name, item.name),
    is_active = COALESCE(:is_active, item.is_active),
    technical_area_id = COALESCE(:technical_area_id, item.technical_area_id),
    updated_at = now()
FROM (
    SELECT id, code, name, is_active, technical_area_id
    FROM unit_types
    WHERE id = :id
    FOR UPDATE
) AS antes
WHERE item.id = antes.id
RETURNING
    item.id, item.code, item.name, item.is_active, item.technical_area_id,
    antes.code AS previous_code,
    antes.name AS previous_name,
    antes.is_active AS previous_is_active,
    antes.technical_area_id AS previous_technical_area_id
