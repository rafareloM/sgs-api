-- Objetivo: as linhas do relatório `trilha_auditoria` para quem tem `auditoria:read` restrito a
--   áreas, distritos ou unidades.
-- Justificativa: fora do escopo global, a trilha é a das unidades do escopo, pela
--   `vw_unit_history` (011/R4.4, 013), que já tira `auth.*`, `acesso.negado` e `auditoria.*`.
--   O filtro de `acesso.*` aqui fecha o mesmo recorte da trilha global.
--   - Não lê `metadata` (005/R4.3); a view já não traz IP, User-Agent nem sessão.
--   - A entidade é sempre a unidade (`entity_type = 'unidade'` na view): outro `entidade_tipo`
--     não traz linha.
--   - Período, prefixo da ação e ordem como na trilha global.
-- Uso: geração do relatório (005/T5), por cursor do servidor em REPEATABLE READ, READ ONLY.
-- Requisitos: 005/R1.3, 005/R4.3
SELECT
    occurred_at,
    action,
    actor_type,
    actor_name,
    actor_roles,
    'unidade' AS entity_type,
    CAST(unit_id AS text) AS entity_id,
    result,
    changes
FROM vw_unit_history
WHERE (:scope_global OR technical_area_id = ANY(CAST(:scope_areas AS smallint[]))
       OR district_id = ANY(CAST(:scope_districts AS smallint[]))
       OR unit_id = ANY(CAST(:scope_units AS uuid[])))
  AND occurred_at >= CAST(:de AS timestamptz)
  AND occurred_at < CAST(:ate AS timestamptz)
  AND action NOT LIKE 'acesso.%'
  AND (CAST(:acao AS text) IS NULL
       OR left(action, char_length(CAST(:acao AS text))) = CAST(:acao AS text))
  AND (CAST(:entidade_tipo AS text) IS NULL OR CAST(:entidade_tipo AS text) = 'unidade')
ORDER BY occurred_at, audit_id
