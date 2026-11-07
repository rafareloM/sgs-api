-- Objetivo: semear os tipos de equipamento citados pelo cliente: UTI móvel (equipamento que não é
--   unidade), Maternidade e Policlínica (equipamentos que uma mesma unidade pode conter).
-- Justificativa: todo equipamento tem tipo (`equipments.equipment_type_code`); sem nenhum tipo,
--   não haveria como cadastrar o primeiro. Exemplos de steering/product.md § Domínio; a lista
--   completa é pergunta em aberto da 006, e o Gestor de Dados inclui os demais pela API
--   (006/R7.2). Domínio fechado (decisão U4 da 011).
-- Uso: `GET /referencias/tipos-equipamento` (006/R7.1) e `equipments.equipment_type_code`.
-- Requisitos: 006/R7.1
INSERT INTO equipment_types (code, name) VALUES
    ('UTI_MOVEL', 'UTI móvel'),
    ('MATERNIDADE', 'Maternidade'),
    ('POLICLINICA', 'Policlínica');
