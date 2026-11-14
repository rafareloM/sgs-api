-- Objetivo: listar os tipos de equipamento, ativos e desativados, na ordem da semeadura (id).
-- Justificativa: a lista preenche os formulários do cadastro (006/R7.1) e é a mesma que o Gestor
--   de Dados mantém (006/R7.2); por isso traz os desativados (exclusão lógica, decisão U5 da 011)
--   com `is_active`, para quem lê escolher só os ativos e o Gestor poder reativá-los.
-- Uso: SqlRepositorioDeReferencias.listar, na rota `GET /referencias/tipos-equipamento` (006/T9).
-- Requisitos: 006/R7.1
SELECT id, code, name, is_active
FROM equipment_types
ORDER BY id
