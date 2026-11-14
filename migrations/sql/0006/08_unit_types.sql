-- Objetivo: tipos de unidade de saúde (CAPS II, USF, Policlínica...), cada um numa área técnica.
-- Justificativa: o tipo é o que liga a unidade à área técnica, e a área é o escopo do
--   Coordenador Técnico (003): sem essa ligação, o COORD_TECNICO não teria como alcançar as
--   unidades da sua área. Desativado em vez de apagado (decisão U5 da 011).
-- Uso: `health_units.unit_type_id`, rotas `/referencias/tipos-unidade` da 006 e escopo `area`.
-- Requisitos: 006/R7.1, 006/R7.2
CREATE TABLE unit_types (
    id smallserial,
    code varchar(50) NOT NULL,
    name varchar(100) NOT NULL,
    technical_area_id smallint NOT NULL,
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_unit_types PRIMARY KEY (id),
    CONSTRAINT uq_unit_types_code UNIQUE (code),
    CONSTRAINT fk_unit_types_technical_area_id_technical_areas
        FOREIGN KEY (technical_area_id) REFERENCES technical_areas (id)
);
