-- Objetivo: função do trigger do log do banco: grava em `db_change_log` cada inclusão,
--   alteração e exclusão de unidade, equipamento e serviço, com as colunas alteradas (de/para),
--   o usuário de banco e se a alteração veio da API.
-- Justificativa: o Auditor precisa ver também o que mudou fora da aplicação (011/R7.1, R7.2).
--   Uma função só para as três tabelas: a linha vira JSON (`to_jsonb`), e coluna nova em
--   qualquer delas entra no log sem mexer aqui.
--   - De/para (011/R7.1): na inclusão, todas as colunas com `de` nulo; na exclusão, todas com
--     `para` nulo; na alteração, só as que mudaram (comparação chave a chave, com IS DISTINCT
--     FROM, para nulo contra valor contar como mudança).
--   - `pending_issues`, `version` e `updated_at` ficam fora em toda operação: não são dado do
--     cadastro (a contagem da validação e o que o trigger de versão escreve). Se numa alteração
--     só elas mudaram, nada é gravado (011/R7.4); o mesmo vale para um UPDATE que não muda nada.
--   - `manager_name` é dado pessoal (LGPD): sai sempre como "***" em `de` e `para`, mesmo vazio,
--     para o log mostrar só que o campo mudou, sem dizer o nome nem se estava preenchido
--     (011/R7.3).
--   - Usuário de banco é o `session_user`, o login que conectou: dentro de SECURITY DEFINER, o
--     `current_user` seria o dono. "Veio da API" é ser membro do `sgs_app` sem ser superusuário,
--     porque o superusuário é membro de todo papel; o login da aplicação não é fixo (`sgs_api`
--     no compose), o papel é (011/R7.2; design da 011 § Decisões).
--   - `txid` junta as linhas de uma mesma transação, como a exclusão de um equipamento e os
--     serviços que o SET NULL desligou dele: cada linha em cascata dispara o trigger da sua
--     tabela e aparece como alteração própria (011/R7.5).
--   - SECURITY DEFINER, com o `sgs_owner` como dono (criada com `SET LOCAL ROLE`, na revisão):
--     o log só aceita escrita do dono, e quem altera o cadastro (inclusive o login da API) não
--     tem privilégio de escrita nele (011/R7.6, R10.2). `search_path` fixo, como toda função
--     DEFINER, para ninguém desviar `jsonb_object_agg` ou a tabela do log com um objeto de mesmo
--     nome noutro schema.
--   - Lê só a linha do trigger (OLD/NEW) e o catálogo (`pg_roles`); não precisa de SELECT no
--     cadastro.
-- Uso: triggers `trg_registry_change_log` de `health_units`, `equipments` e `services` (07 a 09).
-- Requisitos: 011/R7.1, 011/R7.2, 011/R7.3, 011/R7.4, 011/R7.5, 011/R10.2
CREATE FUNCTION trg_registry_change_log() RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
    c_fora_do_log constant text[] := '{pending_issues,version,updated_at}';
    c_dado_pessoal constant text[] := '{manager_name}';
    c_mascarado constant jsonb := '{"de": "***", "para": "***"}';
    v_antiga jsonb;
    v_nova jsonb;
    v_colunas jsonb;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        v_antiga := to_jsonb(OLD) - c_fora_do_log;
    END IF;
    IF TG_OP <> 'DELETE' THEN
        v_nova := to_jsonb(NEW) - c_fora_do_log;
    END IF;

    SELECT jsonb_object_agg(
               coluna,
               CASE
                   WHEN coluna = ANY (c_dado_pessoal) THEN c_mascarado
                   ELSE jsonb_build_object('de', v_antiga -> coluna, 'para', v_nova -> coluna)
               END
           )
      INTO v_colunas
      FROM jsonb_object_keys(coalesce(v_nova, v_antiga)) AS colunas (coluna)
     WHERE (v_antiga -> coluna) IS DISTINCT FROM (v_nova -> coluna);

    IF v_colunas IS NULL THEN
        RETURN NULL;
    END IF;

    INSERT INTO db_change_log
        (table_name, operation, row_id, changed_columns, db_user, via_api, txid)
    VALUES (
        TG_TABLE_NAME,
        TG_OP,
        CAST(coalesce(v_nova, v_antiga) ->> 'id' AS uuid),
        v_colunas,
        session_user,
        pg_has_role(session_user, 'sgs_app', 'MEMBER')
            AND NOT (SELECT rolsuper FROM pg_roles WHERE rolname = session_user),
        txid_current()
    );
    RETURN NULL;
END
$$;
