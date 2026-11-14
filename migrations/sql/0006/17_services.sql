-- Objetivo: serviços de saúde, ofertados numa unidade, num equipamento ou soltos (Sala de
--   Vacinação do Shopping).
-- Justificativa (colunas de docs/architecture/modelo-dados.md § 2):
--   - `unit_id` e `equipment_id` nulos são o serviço solto (006/R6.2); o vínculo é pelo id, nunca
--     pelo nome, então renomear a unidade não desatualiza o serviço (006/R6.4);
--   - FK de `unit_id` com ON DELETE RESTRICT: unidade com serviço não é apagada (011/R9.3);
--   - FK de `equipment_id` com ON DELETE SET NULL: remover o equipamento mantém o serviço,
--     desligado dele e ainda na unidade (011/R9.1);
--   - `in_cnes` diz se o serviço consta no CNES (006/R6.3); muitos não constam, daí o padrão.
-- Uso: casos de uso de serviço da 006 (T8) e consultas de qualidade da 011.
-- Requisitos: 006/R6.1, 006/R6.2, 006/R6.3, 006/R6.4, 011/R9.1, 011/R9.3
CREATE TABLE services (
    id uuid NOT NULL,
    service_type_id smallint NOT NULL,
    unit_id uuid,
    equipment_id uuid,
    name varchar(200) NOT NULL,
    in_cnes boolean NOT NULL DEFAULT false,
    status varchar(20) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_services PRIMARY KEY (id),
    CONSTRAINT fk_services_service_type_id_service_types
        FOREIGN KEY (service_type_id) REFERENCES service_types (id),
    CONSTRAINT fk_services_unit_id_health_units
        FOREIGN KEY (unit_id) REFERENCES health_units (id) ON DELETE RESTRICT,
    CONSTRAINT fk_services_equipment_id_equipments
        FOREIGN KEY (equipment_id) REFERENCES equipments (id) ON DELETE SET NULL
);
