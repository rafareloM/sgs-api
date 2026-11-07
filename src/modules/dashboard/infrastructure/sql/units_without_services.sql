-- Objetivo: listar as unidades não inativas que não têm nenhum serviço cadastrado, no escopo de
--   leitura do usuário e nos filtros opcionais de distrito e de tipo de unidade, paginadas.
-- Justificativa: unidade sem serviço é uma lacuna do cadastro (pilar Validar): ou o serviço
--   existe e não foi cadastrado, ou a unidade não oferta nada e o cadastro dela pede revisão
--   (011/R2.1). Mostra ao Gestor de Dados, e a cada perfil no próprio escopo, onde agir.
--   - Anti join: o LEFT JOIN com `services` mantém toda unidade, e `s.id IS NULL` fica só com as
--     que não acharam par, ou seja, as que não aparecem em `services`. Equivale a NOT EXISTS, e
--     o PostgreSQL planeja os dois como Hash Anti Join.
--   - `status <> 'inativa'` (design da 011): unidade desativada não pede ação; a em implantação
--     entra, porque já deveria ter os serviços cadastrados.
--   - Serviço solto (sem unidade, 006/R6.2) tem `unit_id` nulo e não casa com unidade nenhuma.
--   - O escopo de leitura (spec 003) e os filtros entram como parâmetros num fragmento fixo,
--     aplicado na CTE `units_in_scope`, antes da junção (011/R2.5, R2.7; ADR-0009). A CTE
--     `units` dá à unidade os nomes de coluna do fragmento (`unit_id`, `district_id` e
--     `technical_area_id`, esta pelo tipo da unidade). Nenhum valor do usuário entra no texto.
--   - `count(*) OVER ()` dá o total da consulta na mesma passada, para a paginação.
-- Uso: rota GET /api/v1/dashboard/consultas/unidades-sem-servico (011/T11). O anti join procura
--   os serviços de cada unidade por `ix_services_unit_id`.
-- Requisitos: 011/R2.1, 011/R2.5, 011/R2.7
WITH units AS (
    SELECT
        hu.id AS unit_id,
        hu.name,
        hu.cnes,
        hu.status,
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
    SELECT unit_id, name, cnes, status, unit_type_name, district_name
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
    count(*) OVER () AS total
FROM units_in_scope AS u
LEFT JOIN services AS s ON s.unit_id = u.unit_id
WHERE s.id IS NULL
  AND u.status <> 'inativa'
ORDER BY u.district_name, u.name, u.unit_id
LIMIT :limit OFFSET :offset;
