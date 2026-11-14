-- Objetivo: alterar um item de equipment_types (tipos de equipamento) e devolvê-lo como estava e como ficou.
-- Justificativa:
--   - só os campos enviados mudam: parâmetro nulo mantém o valor (`COALESCE`); a API não deixa
--     enviar nulo nesses campos;
--   - a subconsulta trava a linha (`FOR UPDATE`) e devolve os valores de antes, para o de/para da
--     auditoria (006/R7.2), num comando só; item inexistente não devolve linha (404);
--   - `equipments.equipment_type_code` aponta o código com ON UPDATE CASCADE: o código novo
--     chega a todos os equipamentos do tipo no mesmo comando (011/R9.2);
--   - código repetido viola `uq_equipment_types_code`, e o caso de uso responde 409.
-- Uso: SqlRepositorioDeReferencias.atualizar, na rota `PATCH /referencias/tipos-equipamento/{id}` (006/T9).
-- Requisitos: 006/R7.2, 006/R7.3, 011/R9.2
UPDATE equipment_types AS item
SET code = COALESCE(:code, item.code),
    name = COALESCE(:name, item.name),
    is_active = COALESCE(:is_active, item.is_active),
    updated_at = now()
FROM (
    SELECT id, code, name, is_active
    FROM equipment_types
    WHERE id = :id
    FOR UPDATE
) AS antes
WHERE item.id = antes.id
RETURNING
    item.id, item.code, item.name, item.is_active,
    antes.code AS previous_code,
    antes.name AS previous_name,
    antes.is_active AS previous_is_active
