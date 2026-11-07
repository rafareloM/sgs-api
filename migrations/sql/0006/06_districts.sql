-- Objetivo: completar a tabela de distritos sanitários criada pela 0003 (spec 003) com a exclusão
--   lógica.
-- Justificativa: o Gestor de Dados desativa distritos pela API (006/R7.2) e nenhuma referência é
--   apagada fisicamente (decisão U5 da 011): unidades e escopos de papel (003) continuam
--   apontando para o distrito desativado.
-- Uso: rotas `/referencias/distritos` da 006 e escopo `distrito` do RBAC (003).
-- Requisitos: 006/R7.1, 006/R7.2
ALTER TABLE districts ADD COLUMN is_active boolean NOT NULL DEFAULT true;
