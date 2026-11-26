-- Objetivo: dizer quais ids dos filtros do inventário existem nas referências da 006.
-- Justificativa: um filtro com id inexistente daria um relatório vazio sem aviso; a rota
--   responde 422 no campo (design da 005 § Rotas, `filtros`). Lê só as tabelas de referência,
--   sem escopo; um id nulo conta como existente (o filtro não foi pedido).
-- Uso: POST /api/v1/relatorios (005/T6), antes de gravar o pedido.
-- Requisitos: 005/R1.5
SELECT
    (CAST(:district_id AS smallint) IS NULL
     OR EXISTS (SELECT 1 FROM districts WHERE id = CAST(:district_id AS smallint)))
        AS distrito_id,
    (CAST(:technical_area_id AS smallint) IS NULL
     OR EXISTS (SELECT 1 FROM technical_areas WHERE id = CAST(:technical_area_id AS smallint)))
        AS area_tecnica_id,
    (CAST(:unit_type_id AS smallint) IS NULL
     OR EXISTS (SELECT 1 FROM unit_types WHERE id = CAST(:unit_type_id AS smallint)))
        AS tipo_unidade_id
