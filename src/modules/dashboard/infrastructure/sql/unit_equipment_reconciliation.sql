-- Objetivo: conciliar unidades e equipamentos numa resposta só: os pares unidade-equipamento, as
--   unidades sem equipamento e os equipamentos sem unidade, no escopo de leitura do usuário e nos
--   filtros opcionais de distrito e de tipo de unidade, paginados.
-- Justificativa: unidade e equipamento são cadastros distintos que o cliente confunde (um
--   equipamento pode não ser unidade, como a UTI móvel do SAMU, e uma unidade pode ter dois
--   equipamentos, como Policlínica e Maternidade). Ver os dois lados juntos mostra o que falta
--   ligar (pilar Validar; 011/R2.2).
--   - Full outer join: devolve as linhas que casam (`par`) e também as que sobram de cada lado,
--     com o outro lado nulo. A coluna `situation` diz qual é o caso pelo lado nulo.
--   - Os dois lados são filtrados ANTES da junção, cada um na sua CTE. Se o escopo fosse aplicado
--     depois, o equipamento de uma unidade fora do escopo voltaria como "sem unidade", porque a
--     unidade dele não estaria do lado esquerdo (011/R2.5, R2.6).
--   - Lado das unidades (`units_in_scope`): escopo de leitura (spec 003) e filtros, num fragmento
--     fixo com parâmetros (ADR-0009). A CTE `units` dá à unidade os nomes de coluna do fragmento
--     (`unit_id`, `district_id` e `technical_area_id`, esta pelo tipo da unidade).
--   - Lado dos equipamentos (`equipments_in_scope`): os das unidades no escopo e nos filtros e,
--     só para quem tem escopo global e não filtrou, os sem unidade (011/R2.6). Equipamento sem
--     unidade não tem distrito nem tipo de unidade, então nenhum filtro o seleciona.
--   - Inclui unidades em qualquer status: a conciliação mostra o vínculo, não a situação.
--   - `count(*) OVER ()` dá o total da consulta na mesma passada, para a paginação.
-- Uso: rota GET /api/v1/dashboard/consultas/conciliacao-unidade-equipamento (011/T11).
-- Requisitos: 011/R2.2, 011/R2.5, 011/R2.6, 011/R2.7
WITH units AS (
    SELECT
        hu.id AS unit_id,
        hu.name,
        hu.unit_type_id,
        t.technical_area_id,
        hu.district_id,
        d.name AS district_name
    FROM health_units AS hu
    JOIN unit_types AS t ON t.id = hu.unit_type_id
    JOIN districts AS d ON d.id = hu.district_id
),
units_in_scope AS (
    SELECT unit_id, name, district_name
    FROM units
    WHERE (:scope_global OR technical_area_id = ANY(CAST(:scope_areas AS smallint[]))
           OR district_id = ANY(CAST(:scope_districts AS smallint[]))
           OR unit_id = ANY(CAST(:scope_units AS uuid[])))
      AND (CAST(:district_id AS smallint) IS NULL
           OR district_id = CAST(:district_id AS smallint))
      AND (CAST(:unit_type_id AS smallint) IS NULL
           OR unit_type_id = CAST(:unit_type_id AS smallint))
),
equipments_in_scope AS (
    SELECT e.id, e.unit_id, e.name, et.name AS equipment_type_name
    FROM equipments AS e
    JOIN equipment_types AS et ON et.code = e.equipment_type_code
    WHERE e.unit_id IN (SELECT unit_id FROM units_in_scope)
       OR (e.unit_id IS NULL
           AND :scope_global
           AND CAST(:district_id AS smallint) IS NULL
           AND CAST(:unit_type_id AS smallint) IS NULL)
)
SELECT
    u.unit_id,
    u.name AS unit_name,
    u.district_name,
    e.id AS equipment_id,
    e.name AS equipment_name,
    e.equipment_type_name,
    CASE
        WHEN u.unit_id IS NULL THEN 'equipamento_sem_unidade'
        WHEN e.id IS NULL THEN 'unidade_sem_equipamento'
        ELSE 'par'
    END AS situation,
    count(*) OVER () AS total
FROM units_in_scope AS u
FULL OUTER JOIN equipments_in_scope AS e ON e.unit_id = u.unit_id
ORDER BY u.district_name, u.name, e.name, u.unit_id, e.id
LIMIT :limit OFFSET :offset;
