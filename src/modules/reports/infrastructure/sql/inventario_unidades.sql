-- Objetivo: as linhas do relatório `inventario_unidades`, uma por unidade, no escopo gravado no
--   pedido e com os filtros dele.
-- Justificativa: a `vw_unit_inventory` (011/R4.1) é a definição única do inventário, sem dado
--   pessoal (011/R4.2). Os ids de escopo só filtram e não saem no arquivo.
--   - Escopo pelo fragmento fixo de `src/core/escopo.py`, com o escopo do pedido (005/R1.3).
--   - Os filtros são os de `FiltrosDoInventario`, todos opcionais.
--   - Ordem estável, para o mesmo pedido gerar o mesmo arquivo.
-- Uso: geração do relatório (005/T5), por cursor do servidor em REPEATABLE READ, READ ONLY.
-- Requisitos: 005/R1.3, 011/R4.2
SELECT
    cnes,
    name,
    unit_type_name,
    technical_area_name,
    district_name,
    status,
    registration_status,
    equipment_count,
    service_count,
    services_outside_cnes_count
FROM vw_unit_inventory
WHERE (:scope_global OR technical_area_id = ANY(CAST(:scope_areas AS smallint[]))
       OR district_id = ANY(CAST(:scope_districts AS smallint[]))
       OR unit_id = ANY(CAST(:scope_units AS uuid[])))
  AND (CAST(:district_id AS smallint) IS NULL OR district_id = CAST(:district_id AS smallint))
  AND (CAST(:technical_area_id AS smallint) IS NULL
       OR technical_area_id = CAST(:technical_area_id AS smallint))
  AND (CAST(:unit_type_id AS smallint) IS NULL OR unit_type_id = CAST(:unit_type_id AS smallint))
  AND (CAST(:status AS text) IS NULL OR status = CAST(:status AS text))
ORDER BY district_name, name, unit_id
