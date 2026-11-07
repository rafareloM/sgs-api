-- Objetivo: semear os tipos de serviço do modelo de dados (farmácia, Farmácia da Família, sala de
--   vacina e Espaço Mãe Coruja).
-- Justificativa: todo serviço tem tipo (`services.service_type_id`), e esses são os casos citados
--   pelo cliente (CAPS com farmácia, Sala de Vacinação do Shopping, Espaço Mãe Coruja). O Gestor
--   de Dados inclui os demais pela API (006/R7.2). Domínio fechado (decisão U4 da 011).
-- Uso: `GET /referencias/tipos-servico` (006/R7.1) e `services.service_type_id`.
-- Requisitos: 006/R7.1
INSERT INTO service_types (code, name) VALUES
    ('FARMACIA', 'Farmácia'),
    ('FARMACIA_FAMILIA', 'Farmácia da Família'),
    ('SALA_VACINA', 'Sala de Vacina'),
    ('ESPACO_MAE_CORUJA', 'Espaço Mãe Coruja');
