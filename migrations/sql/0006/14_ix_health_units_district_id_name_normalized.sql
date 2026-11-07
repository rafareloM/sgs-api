-- Objetivo: impedir duas unidades com o mesmo nome normalizado no mesmo distrito sanitário.
-- Justificativa: "Espaço Azul" e "ESPACO  azul" no mesmo distrito são a mesma unidade cadastrada
--   duas vezes, o problema de duplicidade da planilha (006/R1.4). O nome pode se repetir em outro
--   distrito. A coluna vem da `fn_normalize_name`, a mesma regra da busca (011/R5.2).
-- Uso: unicidade na criação e na alteração de unidade (006/T3, T5; o caso de uso devolve 409).
-- Requisitos: 006/R1.4, 011/R5.2
CREATE UNIQUE INDEX ix_health_units_district_id_name_normalized
    ON health_units (district_id, name_normalized);
