-- Objetivo: ligar a unidade ao distrito sanitário e ao tipo de unidade por chave estrangeira.
-- Justificativa: unidade com distrito ou tipo inexistente escaparia do escopo do RBAC (o
--   distrito é o escopo do Técnico Distrital; o tipo leva à área do Coordenador Técnico, 003).
--   Sem cascata: o id de um distrito ou tipo nunca muda (as referências só são desativadas,
--   decisão U5 da 011), e cascata em `districts(id)` mexeria nos escopos (011, design § Decisões).
-- Uso: integridade de `health_units.district_id` e `health_units.unit_type_id`.
-- Requisitos: 006/R1.2
ALTER TABLE health_units
    ADD CONSTRAINT fk_health_units_district_id_districts
        FOREIGN KEY (district_id) REFERENCES districts (id),
    ADD CONSTRAINT fk_health_units_unit_type_id_unit_types
        FOREIGN KEY (unit_type_id) REFERENCES unit_types (id);
