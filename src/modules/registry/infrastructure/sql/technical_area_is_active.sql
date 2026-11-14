-- Objetivo: dizer se uma área técnica existe e está ativa.
-- Justificativa: o tipo de unidade aponta a área técnica, que é o escopo do Coordenador Técnico
--   (003). Conferida antes do INSERT ou UPDATE para responder 422 apontando o campo, e não 500
--   pela chave estrangeira; área desativada (exclusão lógica, decisão U5 da 011) não recebe tipo,
--   como o distrito desativado não recebe unidade (006/T3).
-- Uso: SqlRepositorioDeReferencias.area_ativa, nas rotas de tipo de unidade (006/T9).
-- Requisitos: 006/R7.2
SELECT EXISTS (
    SELECT 1
    FROM technical_areas
    WHERE id = :technical_area_id
      AND is_active
)
