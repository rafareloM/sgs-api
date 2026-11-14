-- Objetivo: histórico de alterações das unidades: quando, quem, o quê, em qual unidade (com
--   distrito e tipo) e a lista {campo, de, para} de cada evento.
-- Justificativa: o Auditor e o Gestor de Dados conferem quem mudou o cadastro de uma unidade e o
--   que mudou (pilar Controlar). A trilha de auditoria (`audit_log`, spec 001) guarda os eventos
--   com o id da entidade e do autor, mas não o nome da unidade, o distrito nem o nome de quem
--   fez; esta view junta isso uma vez, para o histórico da API e os relatórios usarem a mesma
--   definição (011/R4.4).
--   - Junta cinco tabelas: trilha, unidade, tipo, distrito e usuários. O JOIN com a unidade fica
--     só com os eventos de `entity_type = 'unidade'`; `entity_id` é texto na trilha (serve a
--     qualquer entidade), por isso a comparação com `u.id::text`.
--   - Inclui os eventos de equipamentos e serviços da unidade: a 006 os grava no nível da
--     unidade, com `entity_type = 'unidade'` e o id dela (006/R5.3), então já entram pelo mesmo
--     JOIN, sem tabela a mais.
--   - LEFT JOIN com usuários: evento sem autor (tarefa do sistema) continua no histórico, com o
--     autor nulo. O nome do autor vem de `users.display_name`; nenhuma outra coluna de `users`
--     sai daqui (sem e-mail, hash de senha ou segredo do 2FA).
--   - Expõe `unit_id`, `district_id` e `technical_area_id` para o fragmento de escopo de leitura
--     (design da 011, Fluxo). IP e sessão da trilha ficam de fora: o histórico não precisa deles.
--   - O autor e os valores de/para são dados de quem acessa a trilha: a rota que serve esta
--     view exige `auditoria:read` no escopo da unidade, não `dashboard:read` (design da 011,
--     Segurança).
--   - `security_invoker = true`: a view lê a trilha, o cadastro e os usuários com o privilégio de
--     quem consulta, não do dono que a criou (011/R4.6).
-- Uso: consulta `unit_history.sql` da rota `GET /unidades/{id}/historico` (011/T14, 008/R1). O
--   filtro por unidade usa `ix_audit_log_entity` (011/R1.1).
-- Requisitos: 011/R4.4, 011/R4.6
CREATE VIEW vw_unit_history WITH (security_invoker = true) AS
SELECT
    l.id AS audit_id,
    l.occurred_at,
    l.action,
    l.changes,
    l.metadata,
    l.actor_user_id,
    usr.display_name AS actor_name,
    l.actor_roles,
    u.id AS unit_id,
    u.name AS unit_name,
    u.district_id,
    d.name AS district_name,
    t.name AS unit_type_name,
    t.technical_area_id
FROM audit_log AS l
JOIN health_units AS u ON l.entity_type = 'unidade' AND l.entity_id = u.id::text
JOIN unit_types AS t ON t.id = u.unit_type_id
JOIN districts AS d ON d.id = u.district_id
LEFT JOIN users AS usr ON usr.id = l.actor_user_id;
