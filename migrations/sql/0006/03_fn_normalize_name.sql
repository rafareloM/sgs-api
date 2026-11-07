-- Objetivo: normalizar nomes de unidade: sem acento, em minúsculas, sem espaços nas pontas e com
--   espaços repetidos reduzidos a um ("  Espaço  Mãe Coruja" vira "espaco mae coruja").
-- Justificativa: unicidade (006/R1.4) e busca (006/R2.2) precisam concordar sobre quando dois
--   nomes são "o mesmo"; com uma função só no banco, as duas usam a mesma regra (011/R5.2).
--   - Ordem: tira acentos, passa a minúsculas, troca cada sequência de espaço (`\s`: espaço, tab,
--     quebra de linha...) por um espaço e só então apara as pontas. O `btrim` vai por fora porque,
--     sem segundo argumento, ele só tira o espaço comum: aplicado antes, um tab na ponta virava um
--     espaço que ficava no resultado (decisão do Rafael, 07/11/2026; 011, Perguntas em aberto).
--   - IMMUTABLE: a coluna gerada `health_units.name_normalized` só aceita função imutável, e a
--     `unaccent` de um argumento é STABLE (depende do search_path para achar o dicionário). Por
--     isso a chamada é a de dois argumentos, com o dicionário `public.unaccent` explícito.
--   - SET search_path fixo: ninguém troca `lower` ou `unaccent` por outra função pondo um schema
--     na frente do caminho, e o resultado não muda com a sessão.
--   - STRICT: nome nulo dá nulo, sem chamar o corpo. PARALLEL SAFE: pode rodar em consulta
--     paralela.
--   O `domain` da 006 reproduz a mesma regra em Python (`normalizar_nome`), mas a fonte da verdade
--   é esta função.
-- Uso: coluna gerada `health_units.name_normalized` (11_health_units.sql), índices
--   `ix_health_units_district_id_name_normalized` e `ix_health_units_name_normalized_trgm`, e a
--   busca da 006 (`name_normalized ILIKE '%' || fn_normalize_name(:q) || '%'`).
-- Requisitos: 011/R5.1, 011/R5.2, 006/R1.4, 006/R2.2
CREATE FUNCTION fn_normalize_name(p_name text) RETURNS text
LANGUAGE sql
IMMUTABLE
STRICT
PARALLEL SAFE
SET search_path = pg_catalog, public
AS $$
    SELECT btrim(
        regexp_replace(
            lower(public.unaccent('public.unaccent'::regdictionary, p_name)),
            '\s+',
            ' ',
            'g'
        )
    )
$$;
