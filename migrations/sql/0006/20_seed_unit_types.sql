-- Objetivo: semear os tipos de unidade do modelo de dados, cada um na sua área técnica: os de
--   Saúde Mental (CAPS II, CAPS AD, CAPS i, CECON e SIM), a USF na APS e a Policlínica na Média e
--   Alta Complexidade.
-- Justificativa: o tipo é campo obrigatório da unidade (006/R1.2) e decide a área técnica, logo
--   quem pode cadastrá-la (`unidade:create` no escopo da área, 006/R1.1). A área é buscada pelo
--   código, sem depender do id que o banco gerou. Lista provisória até a aba de convenções da
--   planilha (006, Perguntas em aberto). Domínio fechado (decisão U4 da 011).
-- Uso: `GET /referencias/tipos-unidade` (006/R7.1) e `health_units.unit_type_id`.
-- Requisitos: 006/R7.1
INSERT INTO unit_types (code, name, technical_area_id)
SELECT tipo.code, tipo.name, area.id
FROM (
    VALUES
        (1, 'CAPS_II', 'CAPS II', 'SAUDE_MENTAL'),
        (2, 'CAPS_AD', 'CAPS AD', 'SAUDE_MENTAL'),
        (3, 'CAPS_IJ', 'CAPS i', 'SAUDE_MENTAL'),
        (4, 'CECON', 'CECON', 'SAUDE_MENTAL'),
        (5, 'SIM', 'SIM', 'SAUDE_MENTAL'),
        (6, 'USF', 'Unidade de Saúde da Família', 'APS'),
        (7, 'POLICLINICA', 'Policlínica', 'MAC')
) AS tipo (sort_order, code, name, area_code)
JOIN technical_areas AS area ON area.code = tipo.area_code
ORDER BY tipo.sort_order;
