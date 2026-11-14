-- Objetivo: listar o histórico de alterações de uma unidade, com os eventos dos seus
--   equipamentos e serviços, do mais recente ao mais antigo, paginado.
-- Justificativa: o gestor e o Auditor conferem o que mudou numa unidade, quando e por quem
--   (008/R1, pilar Controlar). A consulta lê a `vw_unit_history`, e não o `audit_log` direto,
--   para o histórico da API, os relatórios e o dashboard usarem a mesma definição de evento da
--   unidade, com o nome do autor já resolvido (011/R4.4, R4.5).
--   - Os eventos de equipamento e serviço já estão na view: a 006 os grava no nível da unidade,
--     com `entity_type = 'unidade'` e o id dela (006/R5.3).
--   - Sem fragmento de escopo: a rota só chega aqui depois do `require("auditoria:read")` no
--     escopo desta unidade (spec 003), que responde 403 fora dele (008/R1.4).
--   - Sem eventos de acesso (`acesso.negado`, `auth.*`): a negação de acesso a uma unidade é
--     gravada com ela como entidade (003/R4.6) e entraria pela view, mas evento de acesso é só
--     para quem tem `auditoria:read_acessos` (008/R2.2), e o histórico é de alterações.
--     Decisão registrada em "Perguntas em aberto" da 011.
--   - Filtros opcionais por período, autor e campo (008/R1.3), que se somam; o que não vier
--     chega nulo e não restringe. O período inclui as duas pontas. O campo é procurado na lista
--     {campo, de, para} por contenção de JSONB (`@>`), que acha o evento em que aquele campo
--     aparece entre os alterados. Os valores entram só como parâmetros, com `CAST` para o
--     asyncpg saber o tipo mesmo quando vêm nulos (ADR-0009).
--   - `ORDER BY occurred_at DESC, audit_id DESC`: mais recente primeiro (008/R1.1); o id desempata
--     eventos no mesmo instante, para a paginação não repetir nem pular linha.
--   - `count(*) OVER ()` dá o total da consulta na mesma passada, para a paginação.
-- Uso: rota GET /api/v1/unidades/{id}/historico (011/T14, 008/R1). O filtro pela unidade chega à
--   trilha por `ix_audit_log_entity (entity_type, entity_id, occurred_at DESC)` (011/R1.1).
-- Requisitos: 011/R4.5, 008/R1.1, 008/R1.3
SELECT
    audit_id,
    occurred_at,
    action,
    changes,
    metadata,
    actor_user_id,
    actor_name,
    actor_roles,
    count(*) OVER () AS total
FROM vw_unit_history
WHERE unit_id = :unit_id
  AND action <> 'acesso.negado'
  AND action NOT LIKE 'auth.%'
  AND (CAST(:occurred_from AS timestamptz) IS NULL
       OR occurred_at >= CAST(:occurred_from AS timestamptz))
  AND (CAST(:occurred_to AS timestamptz) IS NULL
       OR occurred_at <= CAST(:occurred_to AS timestamptz))
  AND (CAST(:actor_user_id AS uuid) IS NULL
       OR actor_user_id = CAST(:actor_user_id AS uuid))
  AND (CAST(:changed_field AS text) IS NULL
       OR changes @> jsonb_build_array(jsonb_build_object('campo', CAST(:changed_field AS text))))
ORDER BY occurred_at DESC, audit_id DESC
LIMIT :limit OFFSET :offset;
