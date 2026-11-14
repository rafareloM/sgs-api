-- Objetivo: dizer se um tipo de serviço existe e está ativo, pelo id.
-- Justificativa: o serviço aponta o tipo pelo id (`services.service_type_id`). Conferido antes
--   de gravar para responder 422 apontando o campo, e não 500 pela chave estrangeira; tipo
--   desativado (exclusão lógica, decisão U5 da 011) não recebe serviço novo, como o tipo de
--   equipamento (006/T7) e o tipo de unidade no cadastro da unidade (006/R1.2).
-- Uso: SqlRepositorioDeServicos.tipo_ativo, nos casos de uso de serviço (006/T8).
-- Requisitos: 006/R6.1, 006/R6.2
SELECT EXISTS (
    SELECT 1
    FROM service_types
    WHERE id = :id
      AND is_active
)
