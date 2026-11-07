-- Objetivo: semear os oito distritos sanitários do Recife (DS I a DS VIII).
-- Justificativa: o distrito é campo obrigatório da unidade (006/R1.2) e nível de escopo do
--   Técnico Distrital (003); sem a lista, nenhum formulário de unidade fecha. Lista provisória
--   até a aba de convenções da planilha (006, Perguntas em aberto); o Gestor de Dados ajusta pela
--   API (006/R7.2). Domínio fechado, por isso menos de 30 linhas (decisão U4 da 011).
-- Uso: `GET /referencias/distritos` (006/R7.1) e `health_units.district_id`.
-- Requisitos: 006/R7.1
INSERT INTO districts (code, name) VALUES
    ('DS-I', 'Distrito Sanitário I'),
    ('DS-II', 'Distrito Sanitário II'),
    ('DS-III', 'Distrito Sanitário III'),
    ('DS-IV', 'Distrito Sanitário IV'),
    ('DS-V', 'Distrito Sanitário V'),
    ('DS-VI', 'Distrito Sanitário VI'),
    ('DS-VII', 'Distrito Sanitário VII'),
    ('DS-VIII', 'Distrito Sanitário VIII');
