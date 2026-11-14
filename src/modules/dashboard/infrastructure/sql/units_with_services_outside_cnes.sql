-- Objetivo: listar as unidades que ofertam ao menos um serviço que não consta no CNES, com a
--   quantidade desses serviços, no escopo de leitura do usuário e nos filtros opcionais de
--   distrito e de tipo de unidade, paginadas.
-- Justificativa: serviço fora do CNES é oferta que o cadastro federal não conhece (006/R6.3);
--   saber em que unidades ele está mostra onde atualizar o CNES (pilar Validar; 011/R2.4).
--   - Subconsulta EXISTS correlacionada: para cada unidade, procura um serviço dela com
--     `NOT in_cnes`, e para no primeiro que achar. A unidade entra uma vez só, por mais serviços
--     fora do CNES que tenha, sem GROUP BY nem DISTINCT.
--   - A quantidade vem de uma subconsulta escalar correlacionada no SELECT, só para as unidades
--     que passaram pelo EXISTS.
--   - Serviço solto (sem unidade, 006/R6.2) tem `unit_id` nulo e não casa com unidade nenhuma.
--   - Unidades e serviços em qualquer status, como no design (§ Consultas) e na
--     `vw_unit_inventory` (`services_outside_cnes_count`): serviço removido sai do banco (exclusão
--     física, decisão U5), então o que existe conta.
--   - O escopo de leitura (spec 003) e os filtros entram como parâmetros num fragmento fixo,
--     aplicado na CTE `units_in_scope` (011/R2.5, R2.7; ADR-0009). A CTE `units` dá à unidade os
--     nomes de coluna do fragmento (`unit_id`, `district_id` e `technical_area_id`, esta pelo
--     tipo da unidade). Nenhum valor do usuário entra no texto.
--   - `count(*) OVER ()` dá o total da consulta na mesma passada, para a paginação.
-- Uso: rota GET /api/v1/dashboard/consultas/unidades-servico-fora-cnes (011/T12). As duas
--   subconsultas procuram os serviços de cada unidade por `ix_services_unit_id`.
-- Requisitos: 011/R2.4, 011/R2.5, 011/R2.7
WITH units AS (
    SELECT
        hu.id AS unit_id,
        hu.name,
        hu.cnes,
        hu.unit_type_id,
        t.name AS unit_type_name,
        t.technical_area_id,
        hu.district_id,
        d.name AS district_name
    FROM health_units AS hu
    JOIN unit_types AS t ON t.id = hu.unit_type_id
    JOIN districts AS d ON d.id = hu.district_id
),
units_in_scope AS (
    SELECT unit_id, name, cnes, unit_type_name, district_name
    FROM units
    WHERE (:scope_global OR technical_area_id = ANY(CAST(:scope_areas AS smallint[]))
           OR district_id = ANY(CAST(:scope_districts AS smallint[]))
           OR unit_id = ANY(CAST(:scope_units AS uuid[])))
      AND (CAST(:district_id AS smallint) IS NULL
           OR district_id = CAST(:district_id AS smallint))
      AND (CAST(:unit_type_id AS smallint) IS NULL
           OR unit_type_id = CAST(:unit_type_id AS smallint))
)
SELECT
    u.unit_id,
    u.name,
    u.cnes,
    u.unit_type_name,
    u.district_name,
    (
        SELECT count(*)
        FROM services AS s
        WHERE s.unit_id = u.unit_id
          AND NOT s.in_cnes
    ) AS services_outside_cnes_count,
    count(*) OVER () AS total
FROM units_in_scope AS u
WHERE EXISTS (
    SELECT 1
    FROM services AS s
    WHERE s.unit_id = u.unit_id
      AND NOT s.in_cnes
)
ORDER BY u.district_name, u.name, u.unit_id
LIMIT :limit OFFSET :offset;
