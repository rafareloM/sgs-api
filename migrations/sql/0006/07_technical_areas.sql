-- Objetivo: completar a tabela de áreas técnicas criada pela 0003 (spec 003) com a exclusão
--   lógica.
-- Justificativa: o Gestor de Dados desativa áreas técnicas pela API (006/R7.2) e nenhuma
--   referência é apagada fisicamente (decisão U5 da 011): tipos de unidade e escopos de papel
--   (003) continuam apontando para a área desativada.
-- Uso: rotas `/referencias/areas-tecnicas` da 006 e escopo `area` do RBAC (003).
-- Requisitos: 006/R7.1, 006/R7.2
ALTER TABLE technical_areas ADD COLUMN is_active boolean NOT NULL DEFAULT true;
