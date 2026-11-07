-- Objetivo: tipos de equipamento de saúde (UTI móvel, maternidade...).
-- Justificativa: o equipamento aponta o tipo pelo código (`equipments.equipment_type_code`), e o
--   código é único para que a FK com ON UPDATE CASCADE leve uma correção de código a todos os
--   equipamentos do tipo (011/R9.2). Desativado em vez de apagado (decisão U5 da 011).
-- Uso: `equipments.equipment_type_code` e rotas `/referencias/tipos-equipamento` da 006.
-- Requisitos: 006/R7.1, 006/R7.2, 011/R9.2
CREATE TABLE equipment_types (
    id smallserial,
    code varchar(50) NOT NULL,
    name varchar(100) NOT NULL,
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_equipment_types PRIMARY KEY (id),
    CONSTRAINT uq_equipment_types_code UNIQUE (code)
);
