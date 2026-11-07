-- Objetivo: achar a unidade que já usa um CNES.
-- Justificativa: o CNES é a chave natural da unidade no cadastro federal. Quando a gravação não
--   acontece por conflito (insert_health_unit.sql), o 409 aponta a unidade existente
--   (006/R1.3). A busca exata usa o índice único parcial `ix_health_units_cnes`.
-- Uso: SqlRepositorioDeUnidades.com_cnes, no caso de uso de criar unidade (006/T3).
-- Requisitos: 006/R1.3
SELECT id
FROM health_units
WHERE cnes = :cnes
