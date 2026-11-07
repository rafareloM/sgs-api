# 011 · Recursos de banco de dados · Tarefas

- Status: Aprovado (Rafael, 07/11/2026; aprovação só do dono pela exceção provisória de `steering/sdd-workflow.md`)
- Depende de: 002 (`users`, na `main`); 003 (T1 para as tabelas de referência; T2/T4 para o `require` e a emenda `escopo_de_leitura`); 006 (T1, T5, T6, T9); 008 (T2)
- Issue: #17 · Prazo da disciplina: 13/11/2026

Execução em paralelo (`/implement-spec`): cada tarefa declara "Bloqueada por"; a fronteira é toda tarefa cujos bloqueios estão feitos. Cada tarefa que mexe na 0011 cria **a sua própria revisão do Alembic** (`0011_03_...`, `0011_04_...`), e quem faz o merge na branch de integração ajusta o `down_revision` para a cabeça dela (cadeia linear, sem duas cabeças). No máximo 3 implementadores ao mesmo tempo (cada `make check` sobe um PostgreSQL).

As tarefas de banco (T1 a T10) só dependem das migrações 0003 e 0006 e podem andar antes do `require` da 003. As de rota (T11 a T18) exigem o `require` e o `EscopoLeitura` da 003. Tarefas marcadas "com 006/Tn" vão no mesmo PR da tarefa da 006: uma entrega a regra de negócio, a outra o objeto de banco e o teste da 011.

## Base

- [x] T1. Carregador de `.sql` das migrações e modo offline do Alembic
  - `migrations/sql_loader.py` (escapa `:`, recusa arquivo com mais de uma instrução) e ramo `context.is_offline_mode()` no `migrations/env.py`.
  - Bloqueada por: nenhuma
  - Requisitos: R11.1, R11.2
  - Pronto quando: `tests/unit/migrations/test_sql_loader.py` passa (`'HH24:MI'` e `:=` intactos; duas instruções → erro; `alembic upgrade head --sql` roda sem banco)

- [x] T2. Normalização, colunas e FKs na 0006 (com 006/T1)
  - `fn_normalize_name` (IMMUTABLE, `search_path` fixo, EXECUTE só para `sgs_app`) criada antes de `health_units`; coluna gerada `name_normalized` e índice GIN usando a função; `version` e `pending_issues`; FKs `ON DELETE SET NULL`, `ON UPDATE CASCADE` e `RESTRICT`.
  - Bloqueada por: T1, 003/T1
  - Requisitos: R5.1, R5.2, R9.1, R9.3
  - Pronto quando: `tests/integration/registry/test_normalizacao.py` e `tests/integration/registry/test_integridade.py` passam (inserção pelo login da API inclusive)

## Migração 0011: banco

- [x] T3. Papel dono, privilégios, índices e situação cadastral
  - `sgs_owner NOLOGIN NOSUPERUSER` com `USAGE, CREATE` no schema e o SELECT que as funções precisam; default privileges sem EXECUTE para PUBLIC (`FOR ROLE sgs` e `sgs_owner`); `ix_audit_log_entity`, `ix_services_unit_id`; `fn_registration_status` com GRANT ao `sgs_app`.
  - Bloqueada por: T2
  - Requisitos: R1.1, R1.2, R5.3, R10.1, R10.2
  - Pronto quando: `tests/integration/db/test_privilegios.py` (papel sem login nem superusuário; PUBLIC sem EXECUTE; índices existem) e `tests/integration/registry/test_situacao_cadastral.py` (as quatro situações, na precedência aprovada) passam

- [x] T4. Views de inventário e de histórico
  - `vw_unit_inventory` e `vw_unit_history` com `security_invoker = true`, colunas do design, sem dado pessoal no inventário.
  - Bloqueada por: T3
  - Requisitos: R4.1, R4.2, R4.4, R4.6
  - Pronto quando: `tests/integration/db/test_views.py` passa (contagens do inventário; nenhuma coluna pessoal; eventos de equipamento e serviço no histórico com autor; um papel sem SELECT nas tabelas-base não lê a view)

- [x] T5. Trigger de versão da unidade
  - `trg_health_units_version` (BEFORE UPDATE), ignorando `pending_issues`, `version` e `updated_at`.
  - Bloqueada por: T2
  - Requisitos: R8.1, R8.2
  - Pronto quando: `tests/integration/registry/test_versao_trigger.py` passa (UPDATE direto incrementa versão e `updated_at`; mudança só em `pending_issues` não incrementa)

- [x] T6. Procedimento de desativação
  - `sp_deactivate_unit` com OUT, SQLSTATE `SGS01`, sem COMMIT; GRANT EXECUTE ao `sgs_app`.
  - Bloqueada por: T5
  - Requisitos: R6.1
  - Pronto quando: `tests/integration/registry/test_sp_deactivate_unit.py` passa (pelo login da API: `CALL` devolve status anterior e versão nova; inexistente → SQLSTATE `SGS01`; já inativa → nada muda e a versão é a mesma)

- [x] T7. Log do banco e trigger de log
  - `db_change_log` particionada (criada com `SET LOCAL ROLE sgs_owner`) com a partição DEFAULT; `trg_registry_change_log` (SECURITY DEFINER) nas três tabelas; `sgs_app` só com SELECT.
  - Bloqueada por: T3
  - Requisitos: R7.1, R7.2, R7.3, R7.4, R7.5, R7.6
  - Pronto quando: `tests/integration/audit/test_log_banco.py` (INSERT/UPDATE/DELETE com de/para; superusuário → `via_api = false`; login da API → `true`; `manager_name` mascarado; só `pending_issues` → nenhuma linha; SET NULL e CASCADE geram linhas das filhas) e `tests/integration/audit/test_log_banco_privilegios.py` (login da API sem INSERT, UPDATE, DELETE e TRUNCATE) passam

- [x] T8. Procedimento com cursor das partições e comando administrativo
  - `sp_ensure_monthly_partitions` (cursor explícito, `LOCK` da DEFAULT, `format('%I'/'%L')`, sem DROP), `CALL` na migração com 12 meses e `sgs-admin banco particoes [--meses N]` (cria o ponto de entrada `sgs-admin` com `argparse` se a 002 ainda não o tiver criado).
  - Bloqueada por: T7
  - Requisitos: R6.5, R6.6, R6.7, R6.8, R10.1
  - Pronto quando: `tests/integration/audit/test_particoes.py` (cria os meses faltantes; não apaga nada; DEFAULT com linha de um mês → aviso e mês pulado; a migração deixa 12 meses à frente; login da API não executa o procedimento) e `tests/integration/tools/test_sgs_admin_particoes.py` passam

- [ ] T9. Prova de uso dos índices com volume
  - Fixture de volume (1.000 unidades, ~3.000 serviços, trilha pelo `audit.registrar`) e `EXPLAIN` registrado no cabeçalho dos `.sql` dos índices.
  - Bloqueada por: T3
  - Requisitos: R1.3, R1.4
  - Pronto quando: `tests/integration/db/test_indices.py -m slow` passa (o plano do histórico de uma unidade usa `ix_audit_log_entity`; o dos serviços de uma unidade usa `ix_services_unit_id`)

- [x] T10. TLS entre a API e o PostgreSQL no compose
  - Serviço `db-certs` (CA de dev e certificado com SAN `db` num volume, chave uid 999 e 0600), `ssl=on` e `pg_hba.conf` com `hostssl`/`hostnossl reject`/`local`, API em `verify-full` com a CA montada; README atualizado.
  - Bloqueada por: nenhuma
  - Requisitos: R10.3, R10.4, R10.5
  - Pronto quando: `tests/e2e/test_tls_banco.py -m slow` passa (`/health/ready` 200 com a API em `verify-full`; conexão TCP com `sslmode=disable` recusada; `git ls-files` sem chave nem certificado)

## Rotas (exigem `require` e `EscopoLeitura` da 003)

- [x] T11. Consultas com anti join e full outer join
  - `units_without_services.sql`, `unit_equipment_reconciliation.sql` (lados filtrados antes da junção), porta `ConsultasDashboard`, conferência de filtros contra as referências, rotas e schemas.
  - Bloqueada por: T4, 003/T4
  - Requisitos: R2.1, R2.2, R2.5, R2.6, R2.7, R2.8, R2.9
  - Pronto quando: `tests/integration/dashboard/test_consultas_qualidade.py::test_unidades_sem_servico*` e `::test_conciliacao*` passam (resultado igual ao semeado; escopo distrital reduz; equipamento sem unidade só com escopo global; 403; 422 com distrito inexistente)

- [ ] T12. Consultas com subconsulta
  - `districts_cnes_above_network.sql` (escalar no `HAVING`, "rede" no escopo) e `units_with_services_outside_cnes.sql` (`EXISTS`), rotas e schemas.
  - Bloqueada por: T11
  - Requisitos: R2.3, R2.4, R2.5, R2.7, R2.8, R2.9
  - Pronto quando: `tests/integration/dashboard/test_consultas_qualidade.py::test_distritos_cnes*` e `::test_fora_cnes*` passam (com escopo distrital, a rede é só o distrito)

- [ ] T13. Inventário
  - `unit_inventory.sql` sobre a view, rota e schema.
  - Bloqueada por: T4, T11
  - Requisitos: R4.3
  - Pronto quando: `tests/integration/dashboard/test_inventario.py` passa (contagens e situação cadastral; nenhum campo pessoal; escopo; filtros)

- [ ] T14. Histórico da unidade pela view (com 008/T2)
  - `unit_history.sql` sobre `vw_unit_history` na rota `GET /unidades/{id}/historico` da 008.
  - Bloqueada por: T4, 003/T4
  - Requisitos: R4.5
  - Pronto quando: `tests/integration/audit/test_historico_unidade.py` passa (eventos da unidade, de seus equipamentos e serviços, com autor; 403 fora do escopo)

- [ ] T15. Log do banco e partições na API
  - `db_change_log_list.sql`, `db_change_log_partitions.sql`, rotas `GET /auditoria/banco` e `/auditoria/banco/particoes`.
  - Bloqueada por: T8, 003/T4
  - Requisitos: R6.9, R7.7, R7.8
  - Pronto quando: `tests/integration/audit/test_log_banco_api.py` (filtros por período, tabela e `fora_da_api`; 403 sem escopo global) e `tests/integration/audit/test_particoes_api.py` (intervalo e contagem) passam

- [ ] T16. Desativação pela rota (com 006/T6)
  - Caso de uso chama o procedimento, traduz `SGS01` em `NotFound` e audita só quando muda.
  - Bloqueada por: T6, 006/T3
  - Requisitos: R6.2, R6.3, R6.4
  - Pronto quando: `tests/integration/registry/test_desativar.py` passa (200 com `unidade.desativada` e motivo; 404 sem mensagem do banco; já inativa → 200 sem auditoria)

- [ ] T17. Versão invalidada por alteração fora da API (com 006/T5)
  - Caso de uso da 006 sem incrementar `version`, com `WHERE version = :esperada RETURNING version`.
  - Bloqueada por: T5, 006/T3
  - Requisitos: R8.3
  - Pronto quando: `tests/integration/registry/test_versao_fora_da_api.py` passa (UPDATE pelo superusuário, depois `PATCH` com o ETag antigo → 412)

- [ ] T18. Correção de código de tipo de equipamento (com 006/T9)
  - `PATCH /referencias/tipos-equipamento/{id}` com `codigo`, cascata pela FK e auditoria com a quantidade de equipamentos.
  - Bloqueada por: T2, 003/T4
  - Requisitos: R9.2
  - Pronto quando: `tests/integration/registry/test_referencia_codigo.py` passa (equipamentos com o código novo; `referencia.atualizada` com `equipamentos_afetados`; 409 com código repetido)

- [ ] T19. Catálogo de consultas
  - Lista fixa de descrições (inclui histórico, log e partições) e rota filtrada pelas permissões efetivas.
  - Bloqueada por: T11, T12, T13, T14, T15
  - Requisitos: R3.1, R3.2
  - Pronto quando: `tests/integration/dashboard/test_catalogo.py` passa (campos de cada entrada; sem `auditoria:read`, histórico, log e partições não aparecem)

## Entrega

- [ ] T20. Arquivo SQL único e documentação dos `.sql`
  - `make sql-bd` (DDL offline + consultas com cabeçalho em `build/sql-bd.sql`, no `.gitignore`); teste de arquitetura dos cabeçalhos, nomes e fragmento de escopo; seção da disciplina no README (onde está cada objeto, 30 tuplas, exclusão lógica).
  - Bloqueada por: T1 a T19
  - Requisitos: R1.4, R2.5, R11.1, R11.3, R11.4, R11.5
  - Pronto quando: `tests/tools/test_sql_bd.py` (arquivo com DDL e consultas na ordem das migrações) e `tests/architecture/test_sql_documentado.py` (todo `.sql` com cabeçalho de objetivo, justificativa, uso e requisito; nomes com prefixo; toda consulta do `dashboard` com o fragmento de escopo; todo objeto da 0011 citado em algum teste de integração) passam

## Cobertura
Todos os requisitos de R1.1 a R11.5 aparecem em pelo menos uma tarefa. A R11.5 (teste de integração por objeto) é feita em T2 a T8 e conferida pelo teste de arquitetura da T20.
