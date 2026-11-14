-- Objetivo: ler uma unidade de saúde inteira pelo id.
-- Justificativa: o procedimento de desativação devolve só o status anterior e a versão
--   (011/R6.1), e a resposta traz a unidade completa com o `ETag` da versão (design da 011 §
--   Rotas). Lida depois do CALL, na mesma transação, já mostra o status e a versão que o
--   procedimento e o trigger de versão deixaram. Mesmas colunas do RETURNING de
--   insert_health_unit.sql; a busca usa a chave primária. Na atualização, dá a versão atual
--   (comparada com o `If-Match`) e os valores de antes para o diff da auditoria (006/R3.2, R3.5).
-- Uso: SqlRepositorioDeUnidades.desativar e .ler, nos casos de uso de desativar unidade
--   (006/T6, 011/T16) e de atualizar unidade (006/T5, 011/T17).
-- Requisitos: 006/R4.1, 011/R6.1, 006/R3.2, 006/R3.5
SELECT
    id, name, cnes, unit_type_id, district_id, cep, address, neighborhood, phone,
    manager_name, opening_hours, latitude, longitude, status,
    pending_issues, version, created_at, updated_at
FROM health_units
WHERE id = :id
