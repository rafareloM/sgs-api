-- Objetivo: equipamentos de saúde, ligados a uma unidade ou sem unidade (UTI móvel do SAMU).
-- Justificativa (colunas de docs/architecture/modelo-dados.md § 2):
--   - `unit_id` nulo é o equipamento que não pertence a unidade nenhuma (006/R5.2);
--   - FK de `unit_id` com ON DELETE RESTRICT: apagar a unidade não pode levar junto, nem deixar
--     órfãos, os equipamentos dela (011/R9.3);
--   - o tipo é apontado pelo código, com ON UPDATE CASCADE: corrigir o código de um tipo de
--     equipamento atualiza todos os equipamentos dele (011/R9.2). ON DELETE fica no padrão (NO
--     ACTION), porque tipo em uso não some: é desativado (decisão U5 da 011).
-- Uso: casos de uso de equipamento da 006 (T7), inventário e conciliação da 011.
-- Requisitos: 006/R5.1, 006/R5.2, 011/R9.2, 011/R9.3
CREATE TABLE equipments (
    id uuid NOT NULL,
    unit_id uuid,
    cnes varchar(7),
    name varchar(200) NOT NULL,
    equipment_type_code varchar(50) NOT NULL,
    quantity integer NOT NULL DEFAULT 1,
    status varchar(20) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_equipments PRIMARY KEY (id),
    CONSTRAINT fk_equipments_unit_id_health_units
        FOREIGN KEY (unit_id) REFERENCES health_units (id) ON DELETE RESTRICT,
    CONSTRAINT fk_equipments_equipment_type_code_equipment_types
        FOREIGN KEY (equipment_type_code) REFERENCES equipment_types (code) ON UPDATE CASCADE
);
