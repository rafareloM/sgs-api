-- Objetivo: dizer se um tipo de equipamento existe e está ativo, pelo código.
-- Justificativa: o equipamento aponta o tipo pelo código (`equipments.equipment_type_code`).
--   Conferido antes de gravar para responder 422 apontando o campo, e não 500 pela chave
--   estrangeira; tipo desativado (exclusão lógica, decisão U5 da 011) não recebe equipamento
--   novo, como o tipo de unidade e o distrito no cadastro da unidade (006/R1.2).
-- Uso: SqlRepositorioDeEquipamentos.tipo_ativo, nos casos de uso de equipamento (006/T7).
-- Requisitos: 006/R5.1, 006/R5.2
SELECT EXISTS (
    SELECT 1
    FROM equipment_types
    WHERE code = :code
      AND is_active
)
