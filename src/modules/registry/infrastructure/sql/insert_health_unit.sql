-- Objetivo: gravar uma unidade de saúde nova e devolvê-la como ficou no banco.
-- Justificativa:
--   - `ON CONFLICT DO NOTHING` sem alvo cobre os dois índices únicos da unidade, o do CNES
--     (parcial) e o do nome normalizado no distrito (006/R1.3, R1.4). Se outra requisição gravou a
--     mesma unidade ao mesmo tempo, esta espera aquela terminar e não grava nada, sem abortar a
--     transação; o caso de uso então procura a existente e responde 409, nunca 500;
--   - `name_normalized` não entra no INSERT: é gerada pela `fn_normalize_name` (011/R5.2);
--   - `version`, `pending_issues`, `created_at` e `updated_at` ficam com o padrão do banco; a
--     versão só muda pelo trigger da 011 (R8), nunca pela aplicação;
--   - o RETURNING devolve o recurso completo da resposta 201 (006/R1.1) e os valores da
--     auditoria (006/R1.6) sem uma segunda leitura.
-- Uso: SqlRepositorioDeUnidades.inserir, no caso de uso de criar unidade (006/T3).
-- Requisitos: 006/R1.1, 006/R1.3, 006/R1.4, 006/R1.6
INSERT INTO health_units (
    id, name, cnes, unit_type_id, district_id, cep, address, neighborhood, phone,
    manager_name, opening_hours, latitude, longitude, status
)
VALUES (
    :id, :name, :cnes, :unit_type_id, :district_id, :cep, :address, :neighborhood, :phone,
    :manager_name, :opening_hours, :latitude, :longitude, :status
)
ON CONFLICT DO NOTHING
RETURNING
    id, name, cnes, unit_type_id, district_id, cep, address, neighborhood, phone,
    manager_name, opening_hours, latitude, longitude, status,
    pending_issues, version, created_at, updated_at
