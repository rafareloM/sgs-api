-- Objetivo: listar as unidades de saúde no escopo de leitura do usuário, com busca por texto
--   livre, filtros combináveis, ordenação e paginação, e o total da listagem.
-- Justificativa:
--   - Texto livre (006/R2.2): o trecho, normalizado pela `fn_normalize_name` (011/R5.2), é
--     procurado na coluna gerada `name_normalized`, com a mesma regra da unicidade, então acento,
--     caixa e espaços repetidos não contam; `ILIKE '%...%'` usa o índice GIN de trigramas
--     `ix_health_units_name_normalized_trgm` (006/R2.7). O CNES é procurado pelo trecho como
--     veio. O parâmetro `q_like` é o texto com `\`, `%` e `_` escapados pela aplicação, para
--     serem procurados como caracteres; o parâmetro `q` é o texto original, usado na semelhança.
--   - Filtros opcionais (006/R2.3), cada um ignorado quando nulo: tipo, área técnica (a do tipo
--     da unidade, onde ela está no cadastro), distrito, status e `com_pendencias`
--     (`pending_issues > 0`, mantido pela 007).
--   - O escopo de leitura (spec 003; 006/R2.6) entra pelo fragmento fixo dos parâmetros
--     `scope_*` (design da 011 § Escopo em SQL explícito); a subconsulta expõe `unit_id`,
--     `district_id` e `technical_area_id` com os nomes do fragmento. Nenhum valor do usuário
--     entra no texto.
--   - Ordem (006/R2.4) pelo parâmetro `order_by`: `relevancia` (maior `similarity` primeiro,
--     design § Busca), `distrito` (nome do distrito), `atualizacao` (mais recente primeiro) ou
--     `nome`; o nome normalizado e o id desempatam, para a paginação não repetir nem pular linha.
--   - `count(*) OVER ()` dá o total da listagem na mesma passada; paginação por offset (design
--     § Busca: o volume não justifica cursor).
--   - Mesmas colunas de health_unit_by_id.sql.
-- Uso: SqlRepositorioDeUnidades.buscar, rota GET /api/v1/unidades (006/T4).
-- Requisitos: 006/R2.1, 006/R2.2, 006/R2.3, 006/R2.4, 006/R2.6, 006/R2.7, 011/R5.2
SELECT
    id, name, cnes, unit_type_id, district_id, cep, address, neighborhood, phone,
    manager_name, opening_hours, latitude, longitude, status,
    pending_issues, version, created_at, updated_at,
    count(*) OVER () AS total
FROM (
    SELECT u.*, u.id AS unit_id, t.technical_area_id, d.name AS district_name
    FROM health_units AS u
    JOIN unit_types AS t ON t.id = u.unit_type_id
    JOIN districts AS d ON d.id = u.district_id
) AS u
WHERE (:scope_global OR technical_area_id = ANY(CAST(:scope_areas AS smallint[]))
       OR district_id = ANY(CAST(:scope_districts AS smallint[]))
       OR unit_id = ANY(CAST(:scope_units AS uuid[])))
  AND (CAST(:q_like AS text) IS NULL
       OR name_normalized ILIKE '%' || fn_normalize_name(CAST(:q_like AS text)) || '%'
       OR cnes LIKE '%' || CAST(:q_like AS text) || '%')
  AND (CAST(:unit_type_id AS smallint) IS NULL
       OR unit_type_id = CAST(:unit_type_id AS smallint))
  AND (CAST(:technical_area_id AS smallint) IS NULL
       OR technical_area_id = CAST(:technical_area_id AS smallint))
  AND (CAST(:district_id AS smallint) IS NULL
       OR district_id = CAST(:district_id AS smallint))
  AND (CAST(:status AS text) IS NULL OR status = CAST(:status AS text))
  AND (CAST(:with_pending AS boolean) IS NULL
       OR (pending_issues > 0) = CAST(:with_pending AS boolean))
ORDER BY
    CASE WHEN CAST(:order_by AS text) = 'relevancia'
         THEN similarity(name_normalized, fn_normalize_name(CAST(:q AS text))) END DESC,
    CASE WHEN CAST(:order_by AS text) = 'distrito' THEN district_name END,
    CASE WHEN CAST(:order_by AS text) = 'atualizacao' THEN updated_at END DESC,
    name_normalized,
    id
LIMIT :limit OFFSET :offset;
