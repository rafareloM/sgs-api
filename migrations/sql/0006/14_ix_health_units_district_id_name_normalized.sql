-- Objetivo: impedir duas unidades com o mesmo nome normalizado no mesmo distrito sanitário.
-- Justificativa: "Espaço Azul" e "ESPACO  azul" no mesmo distrito são a mesma unidade cadastrada
--   duas vezes, o problema de duplicidade da planilha (006/R1.4). O nome pode se repetir em outro
--   distrito. A coluna vem da `fn_normalize_name`, a mesma regra da busca (011/R5.2).
-- Plano que comprova o uso (011/R1.4; revisão do /implement-spec): com volume de demonstração
--   (1.000 unidades com CNES, 3.000 serviços e a trilha correspondente, semeados pelo dono do
--   banco) e depois de ANALYZE, `EXPLAIN (COSTS OFF)` da consulta `health_unit_id_by_name.sql` (o 409 do nome repetido no distrito),
--   pelo login da API, sem forçar nada (`enable_seqscan` no padrão). Teste que repete a prova:
--   `tests/integration/db/test_indices.py -m slow`.
--   Plano:
--     Index Scan using ix_health_units_district_id_name_normalized on health_units
--       Index Cond: ((district_id = '<distrito>'::smallint)
--                    AND (name_normalized = '<nome normalizado>'::text))
-- Uso: unicidade na criação e na alteração de unidade (006/T3, T5; o caso de uso devolve 409).
-- Requisitos: 006/R1.4, 011/R5.2
CREATE UNIQUE INDEX ix_health_units_district_id_name_normalized
    ON health_units (district_id, name_normalized);
