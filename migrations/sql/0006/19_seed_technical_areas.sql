-- Objetivo: semear as áreas técnicas citadas no modelo de dados (Saúde Mental, Saúde Bucal, APS
--   e Média e Alta Complexidade).
-- Justificativa: a área técnica é o escopo do Coordenador Técnico (003) e agrupa os tipos de
--   unidade; Saúde Mental é o escopo temático do grupo. O Gestor de Dados inclui as demais pela
--   API (006/R7.2). Domínio fechado, por isso menos de 30 linhas (decisão U4 da 011).
-- Uso: `GET /referencias/areas-tecnicas` (006/R7.1) e `unit_types.technical_area_id`.
-- Requisitos: 006/R7.1
INSERT INTO technical_areas (code, name) VALUES
    ('SAUDE_MENTAL', 'Saúde Mental'),
    ('SAUDE_BUCAL', 'Saúde Bucal'),
    ('APS', 'Atenção Primária à Saúde'),
    ('MAC', 'Média e Alta Complexidade');
