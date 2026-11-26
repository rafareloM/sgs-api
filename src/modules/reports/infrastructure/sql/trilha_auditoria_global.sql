-- Objetivo: as linhas do relatório `trilha_auditoria` para quem tem `auditoria:read` global.
-- Justificativa: com escopo global, a trilha é a do `audit_log` inteiro, menos os eventos de
--   acesso e de auditoria (`auth.*`, `acesso.*`, `auditoria.*`), que pedem
--   `auditoria:read_acessos` (008/R2.2), como na `vw_unit_history` (013).
--   - Não lê `metadata`, `ip`, `user_agent`, `session_id` nem `request_id` (005/R4.3). As
--     mudanças saem como gravadas, com os valores pessoais já em `***`.
--   - Período de `de` (incluído) a `ate` (excluído), em UTC.
--   - O prefixo da ação é comparado por `left()`, e não por LIKE: o `_` é válido no nome da ação
--     e seria curinga do LIKE.
-- Uso: geração do relatório (005/T5), por cursor do servidor em REPEATABLE READ, READ ONLY.
-- Requisitos: 005/R1.3, 005/R4.3
SELECT
    l.occurred_at,
    l.action,
    l.actor_type,
    usr.display_name AS actor_name,
    l.actor_roles,
    l.entity_type,
    l.entity_id,
    l.result,
    l.changes
FROM audit_log AS l
LEFT JOIN users AS usr ON usr.id = l.actor_user_id
WHERE l.occurred_at >= CAST(:de AS timestamptz)
  AND l.occurred_at < CAST(:ate AS timestamptz)
  AND l.action NOT LIKE 'auth.%'
  AND l.action NOT LIKE 'acesso.%'
  AND l.action NOT LIKE 'auditoria.%'
  AND (CAST(:acao AS text) IS NULL
       OR left(l.action, char_length(CAST(:acao AS text))) = CAST(:acao AS text))
  AND (CAST(:entidade_tipo AS text) IS NULL OR l.entity_type = CAST(:entidade_tipo AS text))
ORDER BY l.occurred_at, l.id
