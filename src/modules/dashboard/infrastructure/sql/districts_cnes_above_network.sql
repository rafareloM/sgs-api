-- Objetivo: listar os distritos cujo percentual de unidades sem CNES é maior que o percentual da
--   rede, junto com o percentual da rede, no escopo de leitura do usuário e no filtro opcional de
--   tipo de unidade.
-- Justificativa: unidade sem CNES está fora do cadastro federal (pilar Validar). Comparar cada
--   distrito com a rede mostra onde a lacuna se concentra e onde agir primeiro (011/R2.3).
--   - Subconsulta escalar no HAVING: o GROUP BY dá o percentual de cada distrito, e a subconsulta
--     `(SELECT avg(...) FROM units_in_scope)` dá um valor só, o da rede, que o HAVING compara com
--     cada grupo. `avg((cnes IS NULL)::int)` é a fração de unidades sem CNES.
--   - "A rede" é o conjunto de unidades no escopo do usuário (011/R2.5): a subconsulta lê a mesma
--     CTE `units_in_scope` que os grupos, com o mesmo escopo e o mesmo filtro de tipo. Com escopo
--     de um distrito só, a rede é o próprio distrito, que nunca fica acima de si mesmo.
--   - O escopo de leitura (spec 003) e o filtro entram como parâmetros num fragmento fixo,
--     aplicado na CTE `units_in_scope` (ADR-0009). A CTE `units` dá à unidade os nomes de coluna
--     do fragmento (`unit_id`, `district_id` e `technical_area_id`, esta pelo tipo da unidade).
--     Sem filtro de distrito: a consulta compara os distritos entre si (design da 011 § Rotas).
--   - Unidades em qualquer status, como no design (§ Consultas).
--   - O percentual da rede também vem na resposta, mesmo sem distrito acima dele: a CTE
--     `network` tem sempre uma linha (nula se não há unidade no escopo), e os distritos entram
--     por LEFT JOIN. Percentuais de 0 a 100, com duas casas; a comparação usa o valor exato.
-- Uso: rota GET /api/v1/dashboard/consultas/distritos-cnes-acima-da-media (011/T12).
-- Requisitos: 011/R2.3, 011/R2.5, 011/R2.7
WITH units AS (
    SELECT
        hu.id AS unit_id,
        hu.cnes,
        hu.unit_type_id,
        t.technical_area_id,
        hu.district_id,
        d.name AS district_name
    FROM health_units AS hu
    JOIN unit_types AS t ON t.id = hu.unit_type_id
    JOIN districts AS d ON d.id = hu.district_id
),
units_in_scope AS (
    SELECT unit_id, cnes, district_id, district_name
    FROM units
    WHERE (:scope_global OR technical_area_id = ANY(CAST(:scope_areas AS smallint[]))
           OR district_id = ANY(CAST(:scope_districts AS smallint[]))
           OR unit_id = ANY(CAST(:scope_units AS uuid[])))
      AND (CAST(:unit_type_id AS smallint) IS NULL
           OR unit_type_id = CAST(:unit_type_id AS smallint))
),
network AS (
    SELECT round(100 * avg((cnes IS NULL)::int), 2) AS network_percentage
    FROM units_in_scope
),
districts_above AS (
    SELECT
        district_id,
        district_name,
        count(*) AS unit_count,
        count(*) FILTER (WHERE cnes IS NULL) AS without_cnes_count,
        round(100 * avg((cnes IS NULL)::int), 2) AS percentage
    FROM units_in_scope
    GROUP BY district_id, district_name
    HAVING avg((cnes IS NULL)::int) > (
        SELECT avg((cnes IS NULL)::int)
        FROM units_in_scope
    )
)
SELECT
    n.network_percentage,
    da.district_id,
    da.district_name,
    da.unit_count,
    da.without_cnes_count,
    da.percentage
FROM network AS n
LEFT JOIN districts_above AS da ON true
ORDER BY da.percentage DESC, da.district_name, da.district_id;
