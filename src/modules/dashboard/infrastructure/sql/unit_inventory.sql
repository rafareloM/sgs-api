-- Objetivo: listar o inventário da rede, uma linha por unidade (tipo, área técnica, distrito,
--   status, situação cadastral e as quantidades de equipamentos, serviços e serviços fora do
--   CNES), no escopo de leitura do usuário e nos filtros opcionais de distrito e de tipo de
--   unidade, paginado.
-- Justificativa: o inventário do dashboard mostra a mesma definição que o relatório e as telas,
--   escrita uma vez na `vw_unit_inventory` (011/R4.1, R4.3; pilar Visualizar).
--   - Lê só a view: as junções, os agregados e a situação cadastral (`fn_registration_status`)
--     ficam nela. A view não tem dado pessoal (011/R4.2), e a consulta não acrescenta nenhum.
--   - A view é `security_invoker`: lê as tabelas com o privilégio de quem consulta (011/R4.6).
--   - O escopo de leitura (spec 003) e os filtros entram como parâmetros num fragmento fixo
--     (011/R4.3, R2.7; ADR-0009); a view já expõe `unit_id`, `district_id` e
--     `technical_area_id` com os nomes do fragmento. Nenhum valor do usuário entra no texto.
--   - Unidades em qualquer status: o inventário mostra a rede inteira, e a inativa aparece com a
--     situação `inativa`.
--   - `count(*) OVER ()` dá o total da consulta na mesma passada, para a paginação; `unit_id` no
--     fim da ordenação desempata nomes repetidos em distritos diferentes da mesma página.
-- Uso: rota GET /api/v1/dashboard/consultas/inventario (011/T13).
-- Requisitos: 011/R4.1, 011/R4.2, 011/R4.3, 011/R2.7
SELECT
    unit_id,
    name,
    cnes,
    status,
    registration_status,
    unit_type_id,
    unit_type_name,
    technical_area_id,
    technical_area_name,
    district_id,
    district_name,
    equipment_count,
    service_count,
    services_outside_cnes_count,
    count(*) OVER () AS total
FROM vw_unit_inventory
WHERE (:scope_global OR technical_area_id = ANY(CAST(:scope_areas AS smallint[]))
       OR district_id = ANY(CAST(:scope_districts AS smallint[]))
       OR unit_id = ANY(CAST(:scope_units AS uuid[])))
  AND (CAST(:district_id AS smallint) IS NULL
       OR district_id = CAST(:district_id AS smallint))
  AND (CAST(:unit_type_id AS smallint) IS NULL
       OR unit_type_id = CAST(:unit_type_id AS smallint))
ORDER BY district_name, name, unit_id
LIMIT :limit OFFSET :offset;
