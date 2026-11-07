-- Objetivo: dizer se um distrito sanitário existe e está ativo.
-- Justificativa: o distrito é campo obrigatório da unidade (006/R1.2) e o escopo do Técnico
--   Distrital (003). Conferido antes do INSERT para responder 422 apontando o campo, e não 500
--   pela chave estrangeira; distrito desativado (exclusão lógica, decisão U5 da 011) não recebe
--   unidade nova.
-- Uso: SqlRepositorioDeUnidades.distrito_ativo, no caso de uso de criar unidade (006/T3).
-- Requisitos: 006/R1.2
SELECT EXISTS (
    SELECT 1
    FROM districts
    WHERE id = :district_id
      AND is_active
)
