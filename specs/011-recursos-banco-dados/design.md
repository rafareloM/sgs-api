# 011 · Recursos de banco de dados · Design

- Status: Aprovado (Rafael, 07/11/2026; aprovação só do dono pela exceção provisória de `steering/sdd-workflow.md`)
- Requisitos: requirements.md (Aprovado, Rafael, 06/11/2026) · Issue #17

## Visão geral
Os objetos da disciplina de Banco de Dados ficam no PostgreSQL, como SQL escrito à mão e versionado (ADR-0009), e são expostos pelos módulos que os usam. Não há módulo novo (ADR-0002):

| Módulo | O que recebe desta spec |
|---|---|
| `dashboard` | as 4 consultas (R2), o catálogo (R3), o inventário (R4.1–R4.3) |
| `registry` | `fn_normalize_name` (R5.1–R5.2), uso de `sp_deactivate_unit` (R6.1–R6.4), trigger de versão (R8), FKs (R9) |
| `audit` | `vw_unit_history` (R4.4–R4.5), `db_change_log` e trigger de log (R7), partições (R6.5–R6.9), índice da trilha (R1.1) |
| `core` + `docker/` | TLS do banco (R10.3–R10.5) |
| `migrations/` + `src/tools/` | papel dono, grants (R10.1–R10.2), carregador de `.sql`, `make sql-bd` (R11) |

Dependências: `users` (002/T2, já na `main`), `districts`/`technical_areas`/stub de `health_units` (0003, spec 003) e as tabelas da 006 (0006). As rotas dependem do `require` da 003. A 0011 vem depois da 0006 na cadeia do Alembic.

## Rotas (contrato)

Todas as rotas desta spec são `GET` de leitura, com `require` explícito (sem rota genérica `/{nome}`; o teste de rotas protegidas da 003 cobre cada uma). Listas usam `PaginaOut[T]` da 006 (`itens`, `total`, `pagina`, `tamanho`; padrão 20, máximo 100). Erros em `application/problem+json` (001).

| Método e rota | Permissão | Entrada | Saída | Erros | Requisitos |
|---|---|---|---|---|---|
| `GET /api/v1/dashboard/consultas` | `dashboard:read` | — | `list[ConsultaDescritaOut]`: `slug`, `titulo`, `justificativa`, `rota`, `parametros[]`, `colunas[]`, `permissao`, `grafico_sugerido` | 401, 403 | R3.1, R3.2 |
| `GET /api/v1/dashboard/consultas/unidades-sem-servico` | `dashboard:read` + escopo | `distrito?`, `tipo?`, `pagina`, `tamanho` | `PaginaOut[UnidadeResumoOut]` (`id`, `nome`, `cnes`, `tipo`, `distrito`) | 401, 403, 422 | R2.1, R2.5, R2.7–R2.9 |
| `GET /api/v1/dashboard/consultas/conciliacao-unidade-equipamento` | `dashboard:read` + escopo | `distrito?`, `tipo?`, `pagina`, `tamanho` | `PaginaOut[ConciliacaoOut]` (`unidade_id?`, `unidade_nome?`, `distrito?`, `equipamento_id?`, `equipamento_nome?`, `equipamento_tipo?`, `situacao`: `par` / `unidade_sem_equipamento` / `equipamento_sem_unidade`) | 401, 403, 422 | R2.2, R2.5–R2.9 |
| `GET /api/v1/dashboard/consultas/distritos-cnes-acima-da-media` | `dashboard:read` + escopo | `tipo?` | `DistritosCnesOut`: `percentual_rede`, `distritos[]` (`id`, `nome`, `total_unidades`, `sem_cnes`, `percentual`) | 401, 403, 422 | R2.3, R2.5, R2.7–R2.9 |
| `GET /api/v1/dashboard/consultas/unidades-servico-fora-cnes` | `dashboard:read` + escopo | `distrito?`, `tipo?`, `pagina`, `tamanho` | `PaginaOut[UnidadeForaCnesOut]` (resumo + `servicos_fora_cnes`) | 401, 403, 422 | R2.4, R2.5, R2.7–R2.9 |
| `GET /api/v1/dashboard/consultas/inventario` | `dashboard:read` + escopo | `distrito?`, `tipo?`, `pagina`, `tamanho` | `PaginaOut[InventarioOut]` (colunas da `vw_unit_inventory`, sem dado pessoal) | 401, 403, 422 | R4.1–R4.3 |
| `GET /api/v1/unidades/{id}/historico` (rota da 008/R1, adiantada) | `auditoria:read` no escopo da unidade | filtros da 008/R1.3, `pagina`, `tamanho` | `PaginaOut[EventoHistoricoOut]` | 401, 403, 404 | R4.4, R4.5 |
| `GET /api/v1/auditoria/banco` | `auditoria:read` global | `de?`, `ate?`, `tabela?` (`health_units`/`equipments`/`services`), `fora_da_api?` (bool), `pagina`, `tamanho` | `PaginaOut[AlteracaoBancoOut]` (`ocorrido_em`, `tabela`, `operacao`, `linha_id`, `colunas_alteradas`, `usuario_banco`, `via_api`) | 401, 403, 422 | R7.7, R7.8 |
| `GET /api/v1/auditoria/banco/particoes` | `auditoria:read` global | — | `list[ParticaoOut]` (`nome`, `de`, `ate`, `registros`; a DEFAULT com `de`/`ate` nulos) | 401, 403 | R6.9 |
| `POST /api/v1/unidades/{id}/desativar` (rota da 006/R4) | `unidade:deactivate` | `{motivo}` | `UnidadeOut` + `ETag` | 401, 403, 404, 422 | R6.1–R6.4 |
| `PATCH /api/v1/referencias/tipos-equipamento/{id}` (rota da 006/R7) | `regra_validacao:manage` | `{codigo?, nome?, ativo?}` | item de referência | 401, 403, 404, 409 (código repetido), 422 | R9.2 |

- 422 de filtro (R2.9): formato inválido vem do Pydantic; distrito ou tipo inexistente é conferido pela `application` contra as referências da 006 antes de executar a consulta.
- O catálogo (R3) é uma lista fixa no código, uma entrada por rota de leitura desta spec (inclusive histórico, log e partições). A rota devolve só as entradas cuja `permissao` o usuário tem em algum escopo (R3.2).
- `contracts/openapi.yaml` é regenerado (`make openapi`) no PR de cada tarefa de rota; a tabela de rotas da `arquitetura-conceitual.md` ganha as linhas acima.

## Modelo de dados / migrações

### Onde fica o SQL (R11.1, R11.2)
- **DDL**: `migrations/sql/<revisão>/NN_<nome>.sql`, **uma instrução por arquivo** (o asyncpg prepara toda instrução). A migração chama `executar_sql(<revisão>, <arquivo>)` de `migrations/sql_loader.py`, que escapa `:` (para `'HH24:MI'` e `:=` não virarem parâmetro) e passa a `op.execute(text(...))`. Arquivo de revisão aplicada nunca é editado.
- **Consultas**: `src/modules/<módulo>/infrastructure/sql/<nome>.sql`, lidas uma vez na carga do módulo e executadas com `text()` e parâmetros nomeados.
- Cada arquivo abre com um cabeçalho em comentário: objetivo, justificativa semântica, quem usa e requisito (R11.1). Nomes seguem a convenção de R11.4 (abaixo).

### Convenção de nomes (R11.4)
Inglês, como as tabelas (`steering/structure.md`), com prefixo: `ix_` índice, `vw_` view, `fn_` função, `sp_` procedimento, `trg_` trigger (a função do trigger tem o mesmo nome do trigger). Arquivos de consulta em inglês (`units_without_services.sql`), rotas em português. Entra em `steering/structure.md` § Nomes.

### Na 0006 (emenda da spec 006)
Objetos que a 006 precisa para existir e que esta spec rastreia:
- `CREATE EXTENSION unaccent` e `pg_trgm` (já no design da 006).
- `fn_normalize_name(text) RETURNS text LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE SET search_path = pg_catalog, public`: `btrim(regexp_replace(lower(public.unaccent('public.unaccent'::regdictionary, p_name)), '\s+', ' ', 'g'))` (o `btrim` vai por fora para que tab ou quebra de linha nas pontas também saiam, R5.1; decidido pelo Rafael em 07/11/2026). Usada pela coluna gerada `health_units.name_normalized` (índice único com `district_id`, R5.2) e pelo índice GIN de busca. `REVOKE EXECUTE ... FROM PUBLIC; GRANT EXECUTE ... TO sgs_app` (R10.1).
- Colunas `health_units.version int NOT NULL DEFAULT 1` e `pending_issues int NOT NULL DEFAULT 0 CHECK (pending_issues >= 0)`.
- FKs (R9): `services.equipment_id → equipments(id) ON DELETE SET NULL`; `equipments.equipment_type_code → equipment_types(code) ON UPDATE CASCADE` (`equipment_types.code` único); `equipments.unit_id` e `services.unit_id → health_units(id) ON DELETE RESTRICT` (R9.3).

### Na 0011 (esta spec), em ordem
| # | Objeto | Requisitos |
|---|---|---|
| 1 | Papel `sgs_owner NOLOGIN NOSUPERUSER` (criado se não existir); `GRANT USAGE, CREATE ON SCHEMA public TO sgs_owner`; `GRANT SELECT ON health_units, equipments, services, users, audit_log, districts, unit_types, technical_areas TO sgs_owner` (o que as funções DEFINER leem) | R10.2 |
| 2 | `ALTER DEFAULT PRIVILEGES FOR ROLE sgs REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC` e o mesmo `FOR ROLE sgs_owner` (um arquivo cada) | R10.1 |
| 3 | `ix_audit_log_entity ON audit_log (entity_type, entity_id, occurred_at DESC)` | R1.1 |
| 4 | `ix_services_unit_id ON services (unit_id)` | R1.2 |
| 5 | `fn_registration_status(u health_units) RETURNS text LANGUAGE plpgsql IMMUTABLE`: `IF u.status = 'inativa' THEN 'inativa' ELSIF u.pending_issues > 0 THEN 'com_pendencias' ELSIF u.cnes IS NULL THEN 'sem_cnes' ELSE 'regular'` | R5.3 |
| 6 | `vw_unit_inventory WITH (security_invoker = true)` | R4.1, R4.2, R4.6 |
| 7 | `vw_unit_history WITH (security_invoker = true)` | R4.4, R4.6 |
| 8 | `sp_deactivate_unit(p_unit_id uuid, OUT o_previous_status text, OUT o_version int)` | R6.1 |
| 9 | Tabela `db_change_log`, a partição `db_change_log_default` e os grants, criadas com `SET LOCAL ROLE sgs_owner` | R7.1, R7.6 |
| 10 | `sp_ensure_monthly_partitions(p_table regclass, p_months_ahead int)` `SECURITY DEFINER`, dono `sgs_owner`; a migração chama `CALL sp_ensure_monthly_partitions('db_change_log', 12)` | R6.5–R6.7 |
| 11 | Função `trg_registry_change_log()` `SECURITY DEFINER`, dono `sgs_owner`, e um trigger `AFTER INSERT OR UPDATE OR DELETE FOR EACH ROW` em cada tabela (`health_units`, `equipments`, `services`) | R7.1–R7.5 |
| 12 | Função `trg_health_units_version()` e trigger `BEFORE UPDATE FOR EACH ROW` em `health_units` | R8.1, R8.2 |
| 13 | `REVOKE EXECUTE ... FROM PUBLIC` explícito em cada função e procedimento acima; `GRANT EXECUTE` ao `sgs_app` só em `fn_registration_status` e `sp_deactivate_unit` (as funções de trigger não precisam de EXECUTE para disparar) | R10.1 |

Downgrade: remove na ordem inversa (o `sgs_owner` fica, como o `sgs_app` na 0001: papéis valem para o servidor).

### `vw_unit_inventory`
`health_units u JOIN unit_types t ON t.id = u.unit_type_id JOIN technical_areas a ON a.id = t.technical_area_id JOIN districts d ON d.id = u.district_id`, com `LEFT JOIN` de dois agregados por `unit_id` (equipamentos; serviços e serviços com `in_cnes = false`). Colunas: `unit_id`, `name`, `cnes`, `status`, `registration_status` (`fn_registration_status(u)`), `unit_type_id`, `unit_type_name`, `technical_area_id`, `technical_area_name`, `district_id`, `district_name`, `equipment_count`, `service_count`, `services_outside_cnes_count`. Sem `manager_name`, telefone ou endereço (R4.2). Também é a base do relatório `inventario_unidades` da 005.

### `vw_unit_history`
`audit_log l JOIN health_units u ON l.entity_type = 'unidade' AND l.entity_id = u.id::text JOIN unit_types t ON t.id = u.unit_type_id JOIN districts d ON d.id = u.district_id LEFT JOIN users usr ON usr.id = l.actor_user_id`. Colunas: `audit_id`, `occurred_at`, `action`, `changes`, `metadata`, `actor_user_id`, `actor_name` (`usr.display_name`), `actor_roles`, `unit_id`, `unit_name`, `district_id`, `district_name`, `unit_type_name`, `technical_area_id`. A 006 grava `entity_type = 'unidade'` e `entity_id` da unidade também nos eventos de equipamento e serviço (006/R5.3), então eles aparecem aqui (R4.4).

### `sp_deactivate_unit`
`SELECT status INTO o_previous_status FROM health_units WHERE id = p_unit_id FOR UPDATE`; se não achar, `RAISE EXCEPTION USING ERRCODE = 'SGS01'`. Se já `inativa`, devolve a versão atual sem `UPDATE` (R6.4). Senão, `UPDATE health_units SET status = 'inativa' WHERE id = p_unit_id RETURNING version INTO o_version` (o trigger de versão incrementa). Sem COMMIT: roda na transação da requisição.

### `db_change_log`
```
id bigint GENERATED ALWAYS AS IDENTITY, occurred_at timestamptz NOT NULL DEFAULT clock_timestamp(),
table_name text NOT NULL CHECK (table_name IN ('health_units','equipments','services')),
operation text NOT NULL CHECK (operation IN ('INSERT','UPDATE','DELETE')),
row_id uuid NOT NULL, changed_columns jsonb NOT NULL, db_user text NOT NULL,
via_api boolean NOT NULL, txid bigint NOT NULL,
PRIMARY KEY (id, occurred_at)
) PARTITION BY RANGE (occurred_at)
```
Partições `db_change_log_yAAAAmMM` (`FOR VALUES FROM (início do mês) TO (início do mês seguinte)`, em UTC) e `db_change_log_default` (`DEFAULT`). Dono `sgs_owner`; `sgs_app` só tem `SELECT` na tabela-mãe (R7.6). Índice `(occurred_at DESC)` herdado pelas partições, para a listagem por período.

### `trg_registry_change_log()`
- `changed_columns` = `{coluna: {"de": v, "para": v}}`: no INSERT, todas as colunas com `de` nulo; no DELETE, todas com `para` nulo; no UPDATE, só as que mudaram (comparação de `to_jsonb(OLD)` com `to_jsonb(NEW)` por chave).
- Ignora `pending_issues`, `version` e `updated_at`; se no UPDATE não sobrar coluna, não grava nada (R7.4).
- `manager_name` aparece com `"***"` em `de` e `para` (R7.3).
- `db_user = session_user`; `via_api = pg_has_role(session_user, 'sgs_app', 'member') AND NOT (SELECT rolsuper FROM pg_roles WHERE rolname = session_user)` (R7.2). `session_user` continua sendo o login mesmo dentro de `SECURITY DEFINER`.
- `txid = txid_current()`. Alterações em cascata (SET NULL, CASCADE) disparam o trigger da tabela filha e aparecem como linhas próprias (R7.5).

### `trg_health_units_version()`
Se `to_jsonb(NEW) - '{pending_issues,version,updated_at}'` é diferente do mesmo recorte de `OLD`, faz `NEW.version := OLD.version + 1` e `NEW.updated_at := now()`; senão, devolve `NEW` sem tocar (R8.1, R8.2).

### `sp_ensure_monthly_partitions`
Cursor explícito (`DECLARE c_meses CURSOR FOR ...; OPEN; LOOP FETCH ... EXIT WHEN NOT FOUND; ... CLOSE`) sobre `generate_series(date_trunc('month', now()), date_trunc('month', now()) + p_months_ahead meses, '1 month')` com `LEFT JOIN` às partições existentes de `p_table` (`pg_inherits` + `pg_class`, pelo nome `<tabela>_yAAAAmMM`). Para cada mês sem partição:
1. localiza a DEFAULT por `pg_partitioned_table.partdefid` e faz `LOCK` nela em `SHARE ROW EXCLUSIVE`;
2. se `EXISTS (SELECT 1 FROM ONLY <default> WHERE occurred_at >= início AND occurred_at < fim)`, `RAISE WARNING` com o mês e segue (R6.6);
3. senão, `EXECUTE format('CREATE TABLE %I PARTITION OF %I FOR VALUES FROM (%L) TO (%L)', ...)`.
Nunca faz DROP nem DETACH (R6.5). O comando `sgs-admin banco particoes [--meses N]` (R6.8) conecta com `DATABASE_MIGRATION_URL` e executa o `CALL`.

### Consultas (R2), em `dashboard/infrastructure/sql/`
Todas recebem o fragmento de escopo (ver Fluxo) e os filtros opcionais `(:district_id IS NULL OR district_id = :district_id)`.
- `units_without_services.sql` (anti join): `health_units u LEFT JOIN services s ON s.unit_id = u.id WHERE s.id IS NULL AND u.status <> 'inativa'`.
- `unit_equipment_reconciliation.sql` (full outer join): `(SELECT ... FROM health_units WHERE <escopo> AND <filtros>) u FULL OUTER JOIN (SELECT ... FROM equipments e WHERE e.unit_id IN (unidades no escopo e nos filtros) OR (e.unit_id IS NULL AND :scope_global AND :district_id IS NULL AND :unit_type_id IS NULL)) e ON e.unit_id = u.unit_id`. Os dois lados são filtrados **antes** da junção, senão equipamentos de unidades fora do escopo voltariam como "sem unidade" (R2.5, R2.6).
- `districts_cnes_above_network.sql` (subconsulta escalar no `HAVING`): agrupa as unidades no escopo por distrito e mantém os grupos com `avg((cnes IS NULL)::int) > (SELECT avg((cnes IS NULL)::int) FROM health_units WHERE <escopo> AND <filtros>)`; a subconsulta usa o mesmo escopo, então "a rede" é a do usuário (R2.3, R2.5).
- `units_with_services_outside_cnes.sql` (subconsulta `EXISTS`): unidades no escopo com `EXISTS (SELECT 1 FROM services s WHERE s.unit_id = u.id AND NOT s.in_cnes)`, e a contagem desses serviços.
- `unit_inventory.sql`: `SELECT ... FROM vw_unit_inventory WHERE <escopo> AND <filtros> ORDER BY district_name, name LIMIT :limit OFFSET :offset`.

Consultas de `audit/infrastructure/sql/`: `unit_history.sql` (lê `vw_unit_history WHERE unit_id = :unit_id`, filtros da 008), `db_change_log_list.sql`, `db_change_log_partitions.sql` (catálogo `pg_inherits` + `pg_get_expr(relpartbound)` com `LEFT JOIN` de `SELECT tableoid, count(*) FROM db_change_log GROUP BY tableoid`, que só precisa de SELECT na tabela-mãe).

## Fluxo

### Escopo em SQL explícito
O `scope_filter` da 003 devolve uma expressão SQLAlchemy, que não serve ao SQL escrito à mão (ADR-0009). **Emenda proposta na 003:** além dela, o `access` oferece `escopo_de_leitura(usuario, permissao) -> EscopoLeitura` (domínio: `global_: bool`, `areas`, `distritos`, `unidades`, tuplas de ids). A consulta inclui um fragmento fixo e recebe o escopo como parâmetros:
```
(:scope_global OR technical_area_id = ANY(CAST(:scope_areas AS smallint[]))
 OR district_id = ANY(CAST(:scope_districts AS smallint[]))
 OR unit_id = ANY(CAST(:scope_units AS uuid[])))
```
Nenhum valor do usuário entra na string; as views expõem `unit_id`, `district_id` e `technical_area_id` para isso.

### Consulta (R2–R4)
`rota` (`require("dashboard:read")`) → `application.ConsultarX(filtros, usuario)`: confere os filtros contra as referências (422), obtém o `EscopoLeitura`, chama a porta `ConsultasDashboard` → adaptador executa o `.sql` com `text()` → schema de saída. O catálogo filtra a lista fixa pelas permissões efetivas do usuário.

### Desativação (R6.1–R6.4)
`POST /unidades/{id}/desativar` → `require("unidade:deactivate", Unidade(id))` → caso de uso da 006: `CALL sp_deactivate_unit(CAST(:id AS uuid), NULL, NULL)` devolve `(o_previous_status, o_version)`. O repositório captura `DBAPIError` com `orig.sqlstate == 'SGS01'` e levanta `NotFound` com detalhe fixo (R6.3). Se `o_previous_status == 'inativa'`, responde 200 sem auditoria (R6.4). Senão, `audit.registrar("unidade.desativada", changes=[{campo: "status", de, para: "inativa"}], metadata={motivo})` na mesma transação (R6.2).

### Atualização com versão (R8, emenda da 006)
O caso de uso da 006 deixa de incrementar `version`: faz `UPDATE health_units SET ... WHERE id = :id AND version = :esperada RETURNING version`. Nenhuma linha → 412 (ou 404, se a unidade não existe). Uma alteração feita fora da API já incrementou a versão pelo trigger, então o `If-Match` antigo dá 412 (R8.3).

### Correção de código (R9.2, emenda da 006)
`PATCH /referencias/tipos-equipamento/{id}` com `codigo` novo → `UPDATE equipment_types SET code = :novo` (a FK propaga aos equipamentos) → conta `equipments` com o código novo → `audit.registrar("referencia.atualizada", changes=[{campo: "codigo", de, para}], metadata={equipamentos_afetados: n})`.

### Entregável (R11.3)
`make sql-bd` roda `alembic upgrade head --sql` (modo offline, que imprime todo o DDL, inclusive o dos `.sql` carregados) e acrescenta as consultas de `src/modules/*/infrastructure/sql/` com os cabeçalhos, gerando `build/sql-bd.sql` (no `.gitignore`). O `migrations/env.py` ganha o ramo offline (`context.is_offline_mode()`).

## Segurança
- **Privilégio mínimo (R10.1, R10.2):** EXECUTE revogado de PUBLIC (por default privileges e explícito); `sgs_app` executa só `fn_registration_status` e `sp_deactivate_unit` (e `fn_normalize_name`, da 0006). Funções DEFINER pertencem a `sgs_owner NOLOGIN NOSUPERUSER` e fixam `search_path = pg_catalog, public`. `sgs_owner` só tem o SELECT que as funções precisam, mais INSERT no log por ser dono.
- **Log (R7.3, R7.6):** sem DML para `sgs_app`; `manager_name` mascarado; não há trigger em `users` (hash de senha, segredo do 2FA).
- **Views (R4.2, R4.6):** `security_invoker = true`; inventário sem dado pessoal; o histórico, que mostra autor e de/para, fica com `auditoria:read` no escopo da unidade, não com `dashboard:read`.
- **Erros do banco (R6.3):** SQLSTATE próprio traduzido em `AppError` com detalhe fixo; a mensagem do `RAISE` nunca chega ao cliente (001/R4.3).
- **SQL dinâmico:** o fragmento de escopo e os filtros são texto fixo com parâmetros; o único DDL dinâmico (partições) usa `format('%I'/'%L')` com nomes derivados de datas, não de entrada de usuário.
- **TLS do banco (R10.3–R10.5):**
  - serviço `db-certs` (one-shot, imagem `alpine` com `openssl`) gera, se faltarem, CA de dev e certificado do servidor com SAN `db` num volume nomeado `db-certs`; a chave do servidor fica com dono uid 999 e modo 0600; a chave da CA não é gravada no volume;
  - `db` sobe com `ssl=on`, `ssl_cert_file`, `ssl_key_file` e um `pg_hba.conf` montado: `local all all trust` (healthcheck), `hostssl all all all scram-sha-256`, `hostnossl all all all reject` (R10.4);
  - `api` com `DATABASE_SSL_MODE=verify-full` e `DATABASE_SSL_ROOT_CERT=/certs/ca.crt` (volume somente leitura). Migrações usam a mesma configuração (`create_engine` já monta o `ssl_context`);
  - nada disso vai para o git (R10.5); os testes de integração seguem sem TLS (testcontainers), como hoje.

## Decisões e alternativas
| Decisão | Alternativas descartadas |
|---|---|
| Objetos nos módulos que os usam | Módulo `bd` genérico: junta coisas sem relação de domínio e mexe na ADR-0002 |
| DDL em `.sql`, uma instrução por arquivo, via carregador | DDL em string no `.py`: o professor não acha o SQL; vários comandos por arquivo: falha com asyncpg |
| Rotas explícitas + catálogo | Rota genérica `/{nome}`: a permissão ficaria dentro do handler, fora do teste de arquitetura |
| Escopo como parâmetros (`EscopoLeitura`) | Montar o `WHERE` com strings: risco de injeção; usar o `scope_filter` SQLAlchemy: contraria o ADR-0009 |
| Cursor para partições do log | Revalidar pendências em SQL (duplica a 007); verificar a cadeia de hash em SQL (o JSON canônico é do Python); retenção com DROP (ninguém pediu) |
| Log por trigger em tabela separada | Gravar no `audit_log`: o hash é calculado em Python e quebraria a cadeia |
| `via_api` por papel e não superusuário | `session_user = 'sgs_app'` (é `sgs_api`); só `pg_has_role` (superusuário é membro de tudo) |
| Versão por trigger (aprovado, U16) | Versão só no caso de uso: alteração fora da API não invalidaria o ETag |
| Cascade em `equipment_type_code` | Cascade em `districts(id)`: quebraria os escopos da 003; FK composta serviço × equipamento: lacunas com unidade nula |
| `fn_normalize_name` criada na 0006 | Na 0011: a coluna gerada da 006 não existiria sem ela |

**ADR:** nada aqui contraria a stack. O ADR-0009 (Proposto) recebe consequências novas neste PR: escopo inclui `reports`, organização dos `.sql`, carregador, views da 011 cruzando módulos (só leitura) e escopo por parâmetros.

**Emendas propostas neste PR** (specs em Rascunho): 003 (`escopo_de_leitura`), 006 (0006 com `fn_normalize_name`, colunas, FKs, `entity_type`, versão por trigger, desativação pelo procedimento), 010 (30 usuários fictícios e casos que exercitem cada consulta).

## Riscos
- **Prazo (13/11):** a 0011 depende da 0003 e da 0006, e as rotas, do `require`. Mitigação: as tarefas de banco vêm antes das de rota; mesmo sem rotas, migrações, `.sql` e testes são demonstráveis.
- **Coluna gerada e EXECUTE:** se a avaliação da coluna gerada exigir EXECUTE do usuário que insere, o GRANT a `sgs_app` em `fn_normalize_name` resolve; o teste de inserção com o login da API confirma.
- **Partição faltando:** sem manutenção por mais de 12 meses, os registros caem na DEFAULT e os meses ficam sem partição (aviso, sem perda). Aceitável no horizonte do projeto.
- **`LOCK` da DEFAULT:** bloqueia escritas de cadastro por instantes durante a criação de partição; só acontece na migração e no comando administrativo.
- **Imagem do `db-certs`:** precisa de rede para `apk add` na primeira subida; fixar a versão da imagem.
- **Volume de prova (R1.3):** o `EXPLAIN` só mostra índice com volume; a massa é criada por fixture `slow`, separada do seed da 010.
- **Fragmento de escopo repetido** em cada `.sql`: um teste de arquitetura confere que toda consulta do `dashboard` contém o fragmento.

## Estratégia de testes
Dois seams, ambos sobre o banco por teste do `tests/integration/conftest.py`:

**Seam 1 · API HTTP** (httpx + app; prior art `tests/integration/test_health.py`)
| Teste | Requisitos |
|---|---|
| `dashboard/test_consultas_qualidade.py`: cada consulta devolve exatamente os casos semeados no teste; escopo distrital reduz o resultado e muda "a rede"; equipamento sem unidade só com escopo global; filtros; 403 sem permissão; 422 com distrito inexistente e formato inválido | R2.1–R2.9 |
| `dashboard/test_catalogo.py`: campos de cada entrada; usuário sem `auditoria:read` não vê histórico, log nem partições | R3.1, R3.2 |
| `dashboard/test_inventario.py`: contagens e situação cadastral batem com o semeado; nenhum campo pessoal na resposta; escopo | R4.1–R4.3, R5.3 |
| `audit/test_historico_unidade.py` (008/R1): eventos da unidade e de seus equipamentos e serviços, com autor; 403 fora do escopo | R4.4, R4.5 |
| `audit/test_log_banco_api.py`: filtros por período, tabela e `fora_da_api`; 403 sem escopo global | R7.7, R7.8 |
| `audit/test_particoes_api.py`: lista partições com intervalo e contagem | R6.9 |
| `registry/test_desativar.py`: 200 com auditoria; 404 sem mensagem do banco; já inativa → 200 sem auditoria | R6.1–R6.4 |
| `registry/test_versao_fora_da_api.py`: alteração via superusuário, depois `PATCH` com ETag antigo → 412 | R8.3 |
| `registry/test_referencia_codigo.py`: corrigir código propaga aos equipamentos e audita a quantidade | R9.2 |

**Seam 2 · SQL direto com dois papéis** (login da API e superusuário; prior art `tests/integration/audit/test_audit_immutable.py`)
| Teste | Requisitos |
|---|---|
| `audit/test_log_banco.py`: INSERT/UPDATE/DELETE geram linha com colunas de/para; alteração pelo superusuário marca `via_api = false`; `manager_name` mascarado; mudança só em `pending_issues` não gera linha; SET NULL e CASCADE geram linhas das filhas | R7.1–R7.5 |
| `audit/test_log_banco_privilegios.py`: o login da API não consegue INSERT, UPDATE, DELETE nem TRUNCATE no log | R7.6 |
| `audit/test_particoes.py`: o procedimento cria os meses faltantes; não apaga nada; com linha na DEFAULT para um mês, avisa e pula esse mês; a migração deixa 12 meses à frente | R6.5–R6.7 |
| `registry/test_integridade.py`: excluir equipamento mantém os serviços ligados à unidade; apagar unidade com vínculos falha | R9.1, R9.3 |
| `registry/test_versao_trigger.py`: UPDATE direto incrementa versão e `updated_at`; mudança só em `pending_issues` não incrementa | R8.1, R8.2 |
| `registry/test_normalizacao.py`: casos de acento, caixa, espaços; duas unidades com o mesmo nome normalizado no distrito violam a unicidade; a busca acha "espaco azul" para "Espaço  Azul" | R5.1, R5.2 |
| `db/test_privilegios.py`: o login da API não executa `sp_ensure_monthly_partitions` nem as funções de trigger; executa as três funções liberadas; `sgs_owner` não é superusuário nem tem login | R10.1, R10.2 |
| `db/test_indices.py` (`slow`): com a massa de volume, `EXPLAIN` do histórico de uma unidade e dos serviços de uma unidade usa `ix_audit_log_entity` e `ix_services_unit_id`; com `enable_seqscan = off`, só prova compatibilidade (dito no teste) | R1.1–R1.3 |
| `migrations/test_sql_loader.py` (unidade): `'HH24:MI'` e `:=` passam intactos; arquivo com duas instruções é recusado | R11.1, R11.2 |
| `architecture/test_sql_documentado.py`: todo `.sql` tem cabeçalho com objetivo, justificativa, uso e requisito; nomes seguem a convenção; toda consulta do `dashboard` contém o fragmento de escopo | R1.4, R11.1, R11.4, R2.5 |
| `tools/test_sql_bd.py`: `make sql-bd` gera um arquivo com DDL e consultas na ordem das migrações | R11.3 |

**Smoke do compose** (local enquanto o Actions estiver bloqueado): `/health/ready` responde com a API em `verify-full`; `psql "host=127.0.0.1 sslmode=disable"` dentro do `db` é recusado; `git ls-files` não lista chave nem certificado | R10.3–R10.5

R11.5 fica coberto pelo conjunto: cada consulta, view, função, procedimento e trigger tem pelo menos um teste de integração acima.

## Cobertura dos requisitos
Todos os requisitos de R1.1 a R11.5 aparecem em pelo menos uma seção acima. Nenhum ficou sem cobertura.
