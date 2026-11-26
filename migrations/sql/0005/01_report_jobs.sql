-- Objetivo: pedidos de exportação de relatório, do pedido à conclusão ou falha (spec 005).
-- Justificativa (design da 005 § Modelo de dados; docs/architecture/modelo-dados.md § 4):
--   - `id` em uuid v7, gerado pela aplicação (`src.core.ids`), como nas outras tabelas;
--   - tipo, formato e status em listas fechadas (`CHECK`): os tipos e formatos da R1.2 e o ciclo
--     `pendente` → `gerando` → `concluido` ou `falhou` (R1.1, R2.5, R2.6);
--   - `filters` e `scope_snapshot` em JSONB: os filtros já validados e o escopo de leitura de
--     quem pediu, o único que a geração usa (R1.3);
--   - `storage_version_id` guarda a versão do objeto, para remover exatamente o que foi gravado
--     quando a conferência da gravação falha (R2.8);
--   - `sha256` em hex (64 caracteres, `CHECK`) e a assinatura com algoritmo e `kid` (R5.1);
--   - `error` com até 200 caracteres: só a mensagem genérica, o detalhe vai para o log (R2.6);
--   - `ck_report_jobs_concluido_completo`: `concluido` exige a chave do objeto, o hash e a
--     assinatura, para nenhum relatório concluído ficar sem integridade (R2.5, R5.1, R5.3);
--   - FK para `users` com ON DELETE padrão (NO ACTION): usuário não é apagado, é desativado.
--   A API (`sgs_app`) recebe SELECT, INSERT, UPDATE e DELETE pelos privilégios padrão da 0001.
-- Uso: repositório de pedidos (`reports/infrastructure/repository.py`, 005/T1), caso de uso da
--   geração (005/T5) e rotas de relatórios (005/T6).
-- Requisitos: 005/R1.1, 005/R1.2, 005/R1.3, 005/R2.5, 005/R2.6, 005/R5.1
CREATE TABLE report_jobs (
    id uuid NOT NULL,
    report_type text NOT NULL,
    format text NOT NULL,
    filters jsonb NOT NULL,
    requested_by uuid NOT NULL,
    scope_snapshot jsonb NOT NULL,
    status text NOT NULL,
    storage_bucket text,
    storage_key text,
    storage_version_id text,
    size_bytes bigint,
    sha256 char(64),
    signature text,
    signature_alg text,
    signature_kid text,
    error varchar(200),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz,
    finished_at timestamptz,
    expires_at timestamptz,
    CONSTRAINT pk_report_jobs PRIMARY KEY (id),
    CONSTRAINT fk_report_jobs_requested_by_users FOREIGN KEY (requested_by) REFERENCES users (id),
    CONSTRAINT ck_report_jobs_tipo_valido
        CHECK (report_type IN ('inventario_unidades', 'trilha_auditoria')),
    CONSTRAINT ck_report_jobs_formato_valido CHECK (format IN ('csv', 'xlsx')),
    CONSTRAINT ck_report_jobs_status_valido
        CHECK (status IN ('pendente', 'gerando', 'concluido', 'falhou')),
    CONSTRAINT ck_report_jobs_concluido_completo CHECK (
        status <> 'concluido'
        OR (storage_key IS NOT NULL AND sha256 IS NOT NULL AND signature IS NOT NULL
            AND signature_alg IS NOT NULL AND signature_kid IS NOT NULL)
    ),
    CONSTRAINT ck_report_jobs_sha256_hex CHECK (sha256 ~ '^[0-9a-f]{64}$')
);
