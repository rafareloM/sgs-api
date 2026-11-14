-- Objetivo: incluir um item em equipment_types (tipos de equipamento) e devolvê-lo como ficou no banco.
-- Justificativa: o código é único; `ON CONFLICT (code) DO NOTHING` faz um código repetido não
--   gravar nada, sem abortar a transação, e o caso de uso responde 409, nunca 500. O item nasce
--   ativo (padrão da coluna).
-- Uso: SqlRepositorioDeReferencias.inserir, na rota `POST /referencias/tipos-equipamento` (006/T9).
-- Requisitos: 006/R7.2
INSERT INTO equipment_types (code, name)
VALUES (:code, :name)
ON CONFLICT (code) DO NOTHING
RETURNING id, code, name, is_active
