# Modelo de dados (PostgreSQL)

> Proposta inicial. Chaves primárias são `uuid` (v7, ordenável por tempo) salvo tabelas de referência. Toda tabela tem `created_at` e `updated_at` (`timestamptz`, UTC).

## 1. Identidade e acesso

> `groups`, `user_groups`, `directory_sync_runs` e `oidc_login_requests` vêm da migração `0004_diretorio` (spec 004, T1), que também liga `group_role_mappings.group_id` a `groups.id` (`ON DELETE RESTRICT`). O banco real está em [`docs/banco/04-dicionario-dados.md`](../banco/04-dicionario-dados.md).

```mermaid
erDiagram
  users ||--o{ user_groups : pertence
  groups ||--o{ user_groups : contem
  users ||--o{ role_assignments : recebe
  groups ||--o{ group_role_mappings : mapeia
  group_role_mappings ||--o{ role_assignments : deriva
  roles ||--o{ role_assignments : ""
  roles ||--o{ role_permissions : ""
  permissions ||--o{ role_permissions : ""
  users ||--o{ sessions : abre
  sessions ||--o{ refresh_tokens : ""
  directory_sync_runs }o--|| users : disparada_por
```

| Tabela | Colunas principais | Observações |
|---|---|---|
| `users` | `id`, `username` (único, minúsculo), `email` (único, minúsculo, opcional), `display_name`, `password_hash` (Argon2id; nulo se externo), `source` (`local`/`ldap`/`oidc`), `external_id` (DN ou `sub`; nulo se local), `is_active`, `mfa_enabled`, `mfa_secret_enc`, `mfa_last_step`, `mfa_challenge_jti`, `mfa_failed_attempts`, `failed_logins`, `locked_until`, `last_login_at`, `synced_at`, `authz_version` | Único em (`source`, `external_id`). Nunca é apagado, só desativado. `mfa_last_step` impede reusar o código TOTP (R2.4); `mfa_challenge_jti` e `mfa_failed_attempts` contam os erros por `mfa_token` (R2.6); `authz_version` sobe a cada alteração das atribuições e invalida o cache de permissões (003/R4.5) |
| `groups` | `id`, `name`, `source` (`ldap`/`oidc`), `external_id`, `description`, `is_active`, `synced_at` | Único em (`source`, `external_id`). Nunca é apagado, só desativado |
| `user_groups` | `user_id`, `group_id`, `source` (`ldap`/`oidc`), `created_at` | PK composta; índice em `group_id` |
| `roles` | `id`, `code` (ex.: `GESTOR_UNIDADE`), `name`, `description`, `is_system` | Seed por migração |
| `permissions` | `id`, `code` (`recurso:acao`), `description` | Seed por migração |
| `role_permissions` | `role_id`, `permission_id`, `max_scope` (`global`/`area`/`distrito`/`unidade`) | `max_scope` limita o escopo com que o papel pode exercer a permissão |
| `role_assignments` | `id`, `user_id`, `role_id`, `scope_type`, `scope_id` (nulo se global), `origin` (`direct`/`group`), `group_mapping_id`, `granted_by`, `valid_until` | Derivadas de grupo são recalculadas a cada sync |
| `group_role_mappings` | `id`, `group_id`, `role_id`, `scope_type`, `scope_id`, `created_by` | Configuração feita pelo Admin TI |
| `sessions` | `id`, `user_id`, `amr` (`pwd+otp`/`ldap+otp`/`oidc`), `ip`, `user_agent`, `created_at`, `revoked_at` | `sid` no JWT |
| `refresh_tokens` | `id`, `session_id`, `token_hash` (SHA-256), `family_id`, `expires_at`, `used_at`, `revoked_at` | Rotação e detecção de reuso |
| `directory_sync_runs` | `id`, `kind` (`ldap`), `status`, `started_at`, `finished_at`, `triggered_by`, `users_created/updated/deactivated`, `groups_*`, `conflicts` (JSONB, lista), `error` (genérico) | Histórico da sincronização; uma execução `em_andamento` por vez (`ux_directory_sync_runs_em_andamento`) |
| `oidc_login_requests` | `id`, `state_hash` e `binding_hash` (SHA-256), `nonce`, `code_verifier_enc` (`FieldCipher`), `created_at`, `expires_at`, `used_at` | `state` de uso único (004/R3.7); único em `state_hash` |

## 2. Cadastro governado

```mermaid
erDiagram
  districts ||--o{ health_units : localiza
  unit_types ||--o{ health_units : classifica
  technical_areas ||--o{ unit_types : agrupa
  health_units ||--o{ equipments : possui
  health_units ||--o{ services : oferta
  equipments ||--o{ services : oferta
  service_types ||--o{ services : classifica
  health_units ||--o{ change_requests : "futuro"
```

| Tabela | Colunas principais | Observações |
|---|---|---|
| `districts` | `id` (smallint), `code` (`DS-I`...), `name` | Tabela de referência; lista confirmada com o cliente |
| `technical_areas` | `id`, `code` (`SAUDE_MENTAL`, `SAUDE_BUCAL`, `APS`, `MAC`...), `name` | Escopo do papel `COORD_TECNICO` |
| `unit_types` | `id`, `code` (`CAPS_II`, `CAPS_AD`, `CAPS_IJ`, `CECON`, `SIM`, `USF`, `POLICLINICA`...), `name`, `technical_area_id` | Liga unidade a área técnica |
| `health_units` | `id`, `cnes` (7 dígitos, único quando presente), `name`, `name_normalized` (único), `unit_type_id`, `district_id`, `manager_name`, `cep`, `address`, `neighborhood`, `phone`, `opening_hours` (JSONB), `latitude`, `longitude`, `status` (`ativa`/`inativa`/`em_implantacao`), `pending_issues` (int) | Unicidade por CNES e por nome normalizado (sem acento, minúsculo) evita duplicidade (RF-01) |
| `equipments` | `id`, `unit_id` (nulo para equipamento sem unidade, ex.: UTI móvel), `cnes`, `name`, `equipment_type`, `quantity`, `status` | Atende RF-02 simplificado e o modelo do cliente |
| `service_types` | `id`, `code` (`FARMACIA`, `FARMACIA_FAMILIA`, `SALA_VACINA`, `ESPACO_MAE_CORUJA`...), `name` | Referência |
| `services` | `id`, `service_type_id`, `unit_id` (nulo se "solto"), `equipment_id` (nulo), `name`, `in_cnes` (bool), `status` | Serviço solto, ligado a unidade ou a equipamento, como o cliente descreveu |
| `validation_rules` | `id`, `target` (`health_unit`...), `field`, `rule_type` (`required`/`regex`/`enum`/`range`), `params` (JSONB), `message`, `is_active` | Regras configuráveis pelo Gestor de Dados (complementa as regras fixas em código) |
| `change_requests` *(futuro)* | `id`, `unit_id`, `proposed_by`, `diff` (JSONB), `status`, `reviewed_by`, `reviewed_at`, `comment` | Workflow RF-04; regra "quem propõe não valida" |

Como o vínculo do serviço guarda `unit_id` (e não o nome da unidade), o problema citado pelo cliente do "Espaço Mãe Coruja com nome desatualizado" desaparece: renomear a unidade atualiza todas as visões.

## 3. Auditoria

| Tabela | Colunas | Observações |
|---|---|---|
| `audit_log` | `id` (bigserial), `occurred_at`, `actor_user_id`, `actor_roles` (snapshot), `session_id`, `ip`, `request_id`, `action` (`unidade.update`, `auth.login`, `auth.login_failed`, `relatorio.exportado`...), `entity_type`, `entity_id`, `changes` (JSONB: `[{campo, de, para}]`), `metadata` (JSONB), `prev_hash`, `hash` | Append-only |

- **Imutabilidade:** trigger `BEFORE UPDATE OR DELETE` que lança exceção; o usuário de banco da aplicação só tem `INSERT` e `SELECT` nessa tabela.
- **Encadeamento:** `hash = SHA-256(prev_hash || conteúdo canônico)`. Um endpoint de verificação recalcula a cadeia e aponta adulteração (o protótipo já mostra o hash por evento).
- **Retenção:** 2 anos (RS-05). Sem particionamento: ele exigiria incluir `occurred_at` nas unicidades de `hash`/`prev_hash` e enfraqueceria a cadeia (spec 008, design § Retenção). Backup, restauração e arquivamento: ADR-0013 e `docs/operacao/backup-restauracao.md`.
- **Spec 013:**
  - **Colunas novas.** `actor_type`, `origin`, `user_agent`, `result` e `result_reason` (0013_01), nulas nos eventos anteriores. Entram no conteúdo canônico só quando não são nulas, então os hashes antigos não mudam.
  - **Obrigatoriedade.** `ck_audit_log_origem_obrigatoria` (`actor_type` e `result` obrigatórios) é `NOT VALID` e nunca é validada (0013_02).
  - **Imutabilidade.** Os triggers de imutabilidade do `audit_log` e do `db_change_log` (mãe e cada partição) e o `trg_registry_change_log` ficam `ENABLE ALWAYS` (0013_03).
  - **Histórico da unidade.** A `vw_unit_history` expõe tipo de ator, origem e resultado e exclui `auth.*`, `acesso.negado` e `auditoria.*` (0013_04).
  - **Verificação.** Usa `REPEATABLE READ, READ ONLY` e confere a cabeça (`audit_chain_head`) e, opcionalmente, uma âncora externa (ADR-0012).
- **Dados sensíveis:** `changes` nunca guarda senha, hash ou segredo; campos marcados como sensíveis aparecem como `"***"`.

## 4. Relatórios

| Tabela | Colunas | Observações |
|---|---|---|
| `report_jobs` | `id`, `report_type` (`inventario_unidades`/`trilha_auditoria`), `format` (`csv`/`xlsx`), `filters` (JSONB), `requested_by`, `scope_snapshot` (JSONB), `status` (`pendente`/`gerando`/`concluido`/`falhou`), `storage_bucket`, `storage_key`, `storage_version_id`, `size_bytes`, `sha256` (hex), `signature`, `signature_alg`, `signature_kid`, `error` (até 200), `created_at`, `updated_at`, `started_at`, `finished_at`, `expires_at` | Migração `0005_relatorios` (spec 005). `scope_snapshot` registra com que escopo o relatório foi gerado (R1.3). `storage_version_id` permite remover exatamente o objeto gravado (R2.8). Assinatura, algoritmo e `kid` do hash (R5.1). `CHECK`: `concluido` exige `storage_key`, `sha256` e a assinatura completa. Índices: `(requested_by, created_at DESC)` e parcial em `status` para `pendente`/`gerando` |

## 5. Criptografia de campos

| Campo | Técnica |
|---|---|
| `users.password_hash` | Argon2id (hash, não reversível) |
| `users.mfa_secret_enc` | AES-256-GCM, formato `v{versão}:{nonce_b64}:{ct_b64}`, nonce de 96 bits aleatório por gravação, `AAD = user_id` |
| `refresh_tokens.token_hash` | SHA-256 do token opaco (o token em si nunca é gravado) |
| Demais colunas | Criptografia do volume (infra) + TLS no tráfego |
