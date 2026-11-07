-- Objetivo: inventário da rede, uma linha por unidade: tipo, área técnica, distrito, status,
--   situação cadastral e as quantidades de equipamentos, serviços e serviços fora do CNES.
-- Justificativa: inventário do dashboard, relatório de inventário e telas mostram a mesma
--   definição, escrita uma vez no banco (011/R4.1). Responde à pergunta do pilar Visualizar
--   ("o que a rede tem, onde, e em que situação está o cadastro").
--   - Junta quatro tabelas (unidade, tipo, área técnica, distrito) e dois agregados; a área
--     técnica vem do tipo da unidade, que é onde ela está no cadastro.
--   - Os agregados são calculados por `unit_id` antes da junção (LEFT JOIN de subconsultas com
--     GROUP BY): juntar equipamentos e serviços direto na unidade multiplicaria as linhas
--     (2 equipamentos x 3 serviços = 6) e inflaria as contagens. O LEFT JOIN mantém a unidade
--     sem equipamento ou sem serviço, com contagem 0 (`coalesce`).
--   - Conta todos os equipamentos e serviços ligados à unidade, em qualquer status: equipamento e
--     serviço removidos saem do banco (exclusão física, decisão U5), então o que existe conta.
--     Equipamento sem unidade e serviço solto (006/R5.2 e R6.2) não entram em nenhuma unidade.
--   - Serviço fora do CNES: `in_cnes = false` (`count(*) FILTER`, na mesma passada).
--   - Situação cadastral por `fn_registration_status` (011/R5.3), a mesma do resto do sistema.
--   - Expõe `unit_id`, `district_id` e `technical_area_id` para o fragmento de escopo de leitura
--     das consultas (design da 011, Fluxo; 011/R2.5, R4.3).
--   - Sem dado pessoal (011/R4.2, LGPD em steering/security.md): o nome do gestor
--     (`manager_name`) fica de fora, e também telefone, endereço, CEP, bairro e coordenadas.
--     Quem precisa do contato da unidade usa o detalhe da unidade, com a permissão dele.
--   - `security_invoker = true`: a view lê as tabelas com o privilégio de quem consulta, não do
--     dono que a criou (011/R4.6). Sem isso, um papel com SELECT só na view leria o cadastro
--     inteiro pelo privilégio do dono das migrações.
-- Uso: consulta `unit_inventory.sql` da rota `GET /dashboard/consultas/inventario` (011/T13) e
--   relatório `inventario_unidades` da 005. Serviços por unidade usam `ix_services_unit_id`.
-- Requisitos: 011/R4.1, 011/R4.2, 011/R4.6
CREATE VIEW vw_unit_inventory WITH (security_invoker = true) AS
SELECT
    u.id AS unit_id,
    u.name,
    u.cnes,
    u.status,
    fn_registration_status(u) AS registration_status,
    u.unit_type_id,
    t.name AS unit_type_name,
    t.technical_area_id,
    a.name AS technical_area_name,
    u.district_id,
    d.name AS district_name,
    coalesce(e.equipment_count, 0) AS equipment_count,
    coalesce(s.service_count, 0) AS service_count,
    coalesce(s.services_outside_cnes_count, 0) AS services_outside_cnes_count
FROM health_units AS u
JOIN unit_types AS t ON t.id = u.unit_type_id
JOIN technical_areas AS a ON a.id = t.technical_area_id
JOIN districts AS d ON d.id = u.district_id
LEFT JOIN (
    SELECT unit_id, count(*) AS equipment_count
    FROM equipments
    WHERE unit_id IS NOT NULL
    GROUP BY unit_id
) AS e ON e.unit_id = u.id
LEFT JOIN (
    SELECT
        unit_id,
        count(*) AS service_count,
        count(*) FILTER (WHERE NOT in_cnes) AS services_outside_cnes_count
    FROM services
    WHERE unit_id IS NOT NULL
    GROUP BY unit_id
) AS s ON s.unit_id = u.id;
