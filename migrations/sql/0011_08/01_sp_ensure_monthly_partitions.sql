-- Objetivo: garantir que uma tabela particionada por mês (o log do banco, `db_change_log`) tenha
--   uma partição para cada mês, do mês atual até `p_months_ahead` meses à frente, sem apagar
--   nenhuma partição.
-- Justificativa: o log do banco só cresce (011/R7.1). Com uma partição por mês, a consulta por
--   período (011/R7.7) lê só os meses pedidos; sem ela, tudo cai na partição DEFAULT, que vira
--   uma tabela única e grande. O procedimento cria os meses que faltam e é chamado na migração
--   (12 meses, próximo arquivo) e pelo comando `sgs-admin banco particoes [--meses N]`
--   (011/R6.5, R6.7, R6.8).
--   - Cursor explícito (DECLARE, OPEN, FETCH, CLOSE) sobre os meses que ainda não têm partição:
--     `generate_series` do mês atual ao último pedido, com LEFT JOIN às partições que existem
--     (`pg_inherits` + `pg_class`, pelo nome `<tabela>_yAAAAmMM`, o mesmo que o filtro
--     `incluir_no_autogenerate` de `src/core/db.py` reconhece). Cada linha do cursor é um mês a
--     tratar, um de cada vez.
--   - Meses em UTC: o início do mês é calculado sobre `now() AT TIME ZONE 'UTC'` e os limites
--     vão ao CREATE como texto ISO com `+00`, então o fuso e o DateStyle da sessão não mudam o
--     intervalo de nenhuma partição.
--   - Antes de criar o mês, LOCK da DEFAULT (achada por `pg_partitioned_table.partdefid`) em
--     SHARE ROW EXCLUSIVE: ninguém grava nela entre a conferência e a criação. Se a DEFAULT já
--     tem registro daquele mês (o mês ficou sem partição e o log seguiu gravando), o PostgreSQL
--     recusaria a partição nova; o procedimento avisa (RAISE WARNING), pula o mês e segue com os
--     demais, sem perder nem mover registros (011/R6.6). Mover registros exigiria apagar linhas
--     do log, que é só de inclusão.
--   - Nunca faz DROP nem DETACH: partições antigas e as que já existem ficam como estão
--     (011/R6.5). Cada partição criada sai com um NOTICE, que o comando administrativo mostra.
--   - A coluna de partição e o schema vêm do catálogo, e todo identificador entra no SQL
--     dinâmico por `format('%I')`, os limites por `format('%L')` e os valores da conferência
--     por USING: nada vem de entrada de usuário (design da 011 § Segurança).
--   - SECURITY DEFINER, com o `sgs_owner` como dono (criado com `SET LOCAL ROLE`, na revisão): o
--     `sgs_owner` é o dono do log e das partições, e a partição criada nasce dele, sem os
--     default privileges da 0001 que dariam DML ao `sgs_app` (011/R7.6, R10.2). `search_path`
--     fixo, como toda função DEFINER. Sem COMMIT: roda na transação de quem chama.
--   - EXECUTE só para o dono (próximo arquivo): nem PUBLIC nem o login da API criam partições
--     (011/R10.1).
-- Uso: a migração 0011_08 (`CALL sp_ensure_monthly_partitions('db_change_log', 12)`) e o
--   comando `sgs-admin banco particoes [--meses N]` (`src/tools/sgs_admin.py`), que conecta com
--   DATABASE_MIGRATION_URL.
-- Requisitos: 011/R6.5, 011/R6.6, 011/R6.7, 011/R6.8, 011/R10.2
CREATE PROCEDURE sp_ensure_monthly_partitions(p_table regclass, p_months_ahead integer)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
    v_schema name;
    v_tabela name;
    v_chave name;
    v_default name;
    v_mes record;
    v_de text;
    v_ate text;
    v_ocupado boolean;
    c_meses CURSOR FOR
        SELECT meses.inicio,
               meses.inicio + interval '1 month' AS fim,
               v_tabela || to_char(meses.inicio, '"_y"YYYY"m"MM') AS particao
          FROM generate_series(
                   date_trunc('month', now() AT TIME ZONE 'UTC'),
                   date_trunc('month', now() AT TIME ZONE 'UTC')
                       + make_interval(months => p_months_ahead),
                   interval '1 month'
               ) AS meses (inicio)
          LEFT JOIN (pg_inherits herda JOIN pg_class existente ON existente.oid = herda.inhrelid)
                 ON herda.inhparent = p_table
                AND existente.relname = v_tabela || to_char(meses.inicio, '"_y"YYYY"m"MM')
         WHERE existente.oid IS NULL
         ORDER BY meses.inicio;
BEGIN
    IF p_months_ahead IS NULL OR p_months_ahead < 0 THEN
        RAISE EXCEPTION 'sp_ensure_monthly_partitions: informe 0 ou mais meses à frente'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;

    SELECT esquema.nspname, mae.relname, chave.attname, padrao.relname
      INTO v_schema, v_tabela, v_chave, v_default
      FROM pg_partitioned_table particionada
      JOIN pg_class mae ON mae.oid = particionada.partrelid
      JOIN pg_namespace esquema ON esquema.oid = mae.relnamespace
      JOIN pg_attribute chave
        ON chave.attrelid = particionada.partrelid
       AND chave.attnum = particionada.partattrs[0]
      LEFT JOIN pg_class padrao ON padrao.oid = particionada.partdefid
     WHERE particionada.partrelid = p_table
       AND particionada.partstrat = 'r'
       AND particionada.partnatts = 1;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'sp_ensure_monthly_partitions: % não é particionada por intervalo de uma coluna', p_table
            USING ERRCODE = 'invalid_parameter_value';
    END IF;

    OPEN c_meses;
    LOOP
        FETCH c_meses INTO v_mes;
        EXIT WHEN NOT FOUND;

        IF v_default IS NOT NULL THEN
            EXECUTE format('LOCK TABLE %I.%I IN SHARE ROW EXCLUSIVE MODE', v_schema, v_default);
            EXECUTE format(
                'SELECT EXISTS (SELECT 1 FROM ONLY %I.%I WHERE %I >= $1 AND %I < $2)',
                v_schema, v_default, v_chave, v_chave
            )
               INTO v_ocupado
              USING v_mes.inicio AT TIME ZONE 'UTC', v_mes.fim AT TIME ZONE 'UTC';
            IF v_ocupado THEN
                RAISE WARNING '%: o mês % já tem registros na partição %; a partição % não foi criada e os registros ficam onde estão',
                    v_tabela, to_char(v_mes.inicio, 'YYYY-MM'), v_default, v_mes.particao;
                CONTINUE;
            END IF;
        END IF;

        v_de := to_char(v_mes.inicio, 'YYYY-MM-DD HH24:MI:SS') || '+00';
        v_ate := to_char(v_mes.fim, 'YYYY-MM-DD HH24:MI:SS') || '+00';
        EXECUTE format(
            'CREATE TABLE %I.%I PARTITION OF %I.%I FOR VALUES FROM (%L) TO (%L)',
            v_schema, v_mes.particao, v_schema, v_tabela, v_de, v_ate
        );
        RAISE NOTICE 'partição % criada (% a %)', v_mes.particao, v_de, v_ate;
    END LOOP;
    CLOSE c_meses;
END
$$;
