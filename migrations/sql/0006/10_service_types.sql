-- Objetivo: tipos de serviço de saúde (farmácia, sala de vacina, Espaço Mãe Coruja...).
-- Justificativa: classifica serviços ligados a unidade, a equipamento ou soltos, com a mesma
--   lista para todos os formulários. Desativado em vez de apagado (decisão U5 da 011).
-- Uso: `services.service_type_id` e rotas `/referencias/tipos-servico` da 006.
-- Requisitos: 006/R7.1, 006/R7.2
CREATE TABLE service_types (
    id smallserial,
    code varchar(50) NOT NULL,
    name varchar(100) NOT NULL,
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_service_types PRIMARY KEY (id),
    CONSTRAINT uq_service_types_code UNIQUE (code)
);
