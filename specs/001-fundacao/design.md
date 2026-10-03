# 001 · Fundação da API · Design

- Status: Aprovado (Rafael, 03/10/2026)

## Visão geral
Projeto `sgs-api` gerenciado com `uv`, código direto em `src/` (o pacote importável é `src`), testes em `tests/`. O app é criado por uma fábrica `create_app(settings)` para permitir testes com configurações diferentes.

## Estrutura
Ver `steering/structure.md`. Nesta spec nascem: `core/config.py`, `core/db.py`, `core/errors.py`, `core/logging.py`, `core/security_headers.py`, `modules/audit/`, `migrations/`, `docker/`, `.github/workflows/ci.yml`.

## Configuração (`core/config.py`)
`Settings(BaseSettings)`, lida só de variáveis de ambiente (sem arquivo `.env` dentro da aplicação), com grupos: `app` (`APP_ENV`, `DEBUG`, `LOG_LEVEL`, `CORS_ORIGINS`) e `db` (`DATABASE_URL`, `DATABASE_MIGRATION_URL`, `DATABASE_SSL_MODE`, `DATABASE_SSL_ROOT_CERT`, pool) nesta spec; `jwt` e `crypto` entram na 002; `ldap`, `oidc` e `s3` nas 004 e 005. Validadores implementam R2.3: em `prod`, recusa `DEBUG` ligado, TLS diferente de `verify-full` e senha de exemplo nas URLs do banco (as do `.env.example` e do compose, ou qualquer senha com "troque", "exemplo", "example" ou "changeme"). `load_settings()` converte os erros em mensagens que nomeiam a variável, sem ecoar o valor recebido.

## Banco (`core/db.py`)
- `create_async_engine` com asyncpg e `pool_pre_ping`. O TLS segue `DATABASE_SSL_MODE` (`disable`, `require` ou `verify-full`, sempre TLS 1.2 ou superior); em `prod` só vale `verify-full` (R2.3).
- Dois usuários de banco: a API conecta com `DATABASE_URL`, um login membro do papel `sgs_app`; as migrações usam `DATABASE_MIGRATION_URL`, o dono do banco. Em `dev` a subida migra no lifespan (R1.2), com `pg_advisory_xact_lock` para instâncias simultâneas migrarem uma de cada vez; em `test` e `prod` migrar é um passo à parte (`alembic upgrade head`).
- Dependência `get_session()` abre `AsyncSession`; casos de uso usam `async with session.begin()`. Entra com a primeira rota que precisar de sessão.
- Alembic com `env.py` assíncrono. A migração `0001_base` cria o papel `sgs_app` (sem login) com privilégios padrão de DML nas tabelas futuras, `audit_log`, `audit_chain_head`, a função e os triggers de imutabilidade (BEFORE UPDATE/DELETE por linha e BEFORE TRUNCATE) e revoga de `sgs_app` UPDATE, DELETE e TRUNCATE em `audit_log`: a API só insere e lê a trilha.

## Erros (`core/errors.py`)
Hierarquia `AppError(status, type, title)` → `NotFound`, `Forbidden`, `Conflict`, `DomainValidationError`. Handlers para `AppError`, `RequestValidationError` (traduz mensagens do Pydantic para português) e `Exception`.

## Auditoria (`modules/audit`)
- `domain/entry.py`: `AuditEntry` (com `Ator`, `Entidade` e `Mudanca`) e o hash canônico: `hash = SHA-256(prev_hash || JSON)`, com o JSON de chaves ordenadas, sem espaços, em UTF-8, data em UTC com microssegundos e IP normalizado. `domain/ports.py`: porta `AuditStore`.
- `application/registrar.py`: `registrar(store, acao, ator, entidade, mudancas, metadados)` trava a linha de controle `audit_chain_head` (pela porta `AuditStore`, cujo repositório faz `SELECT ... FOR UPDATE`) para serializar o encadeamento, monta o registro e grava na transação de quem chamou. Os outros módulos importam tudo daqui (os tipos do domain são reexportados).
- `infrastructure/`: tabelas (SQLAlchemy Core) e `SqlAuditStore`. `prev_hash` é único no banco, então a cadeia não bifurca.

## Segurança transversal (`core/security_headers.py`, `main.py`)
- `Strict-Transport-Security`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer` e `Cache-Control: no-store` em todas as respostas, não só nas autenticadas (R6.1, opção mais restritiva). Uma rota pode definir o próprio `Cache-Control`.
- CORS só para `CORS_ORIGINS`, com credenciais (cookie do refresh na 002), métodos e cabeçalhos explícitos (R6.2).
- `/openapi.json`, `/docs` e `/redoc` só em `dev` e `test` (R6.3).

## Docker
`docker/compose.yml` com serviços `api`, `db` (postgres:17) e `proxy` (Caddy com TLS interno). Os serviços `ldap` (OpenLDAP com seed LDIF), `keycloak` (26.x, realm importado de `docker/keycloak/realm-sgs.json`) e `s3` (SeaweedFS) entram no compose nas specs 004 (T8) e 005 (T8). Override `compose.test.yml` para CI.

## CI
Ver `.github/workflows/ci.yml` (modelo já incluso neste pacote).

## Estratégia de testes
- Unidade: hash da auditoria, validadores de config.
- Integração (testcontainers): trigger impede UPDATE/DELETE; `/health/ready` com banco parado retorna 503.
- Contrato: schemathesis sobre `/openapi.json`.
