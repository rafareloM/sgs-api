# 001 · Fundação da API · Design

- Status: Aprovado (Leonardo, 03/10/2026)

## Visão geral
Projeto `sgs-api` gerenciado com `uv`, código em `src/sgs_api`, testes em `tests/`. O app é criado por uma fábrica `create_app(settings)` para permitir testes com configurações diferentes.

## Estrutura
Ver `steering/structure.md`. Nesta spec nascem: `core/config.py`, `core/db.py`, `core/errors.py`, `core/logging.py`, `core/security_headers.py`, `modules/audit/`, `migrations/`, `docker/`, `.github/workflows/ci.yml`.

## Configuração (`core/config.py`)
`Settings(BaseSettings)`, lida só de variáveis de ambiente (sem arquivo `.env` dentro da aplicação), com grupos: `app` (`APP_ENV`, `DEBUG`, `LOG_LEVEL`, `CORS_ORIGINS`) e `db` (`DATABASE_URL`, `DATABASE_MIGRATION_URL`, `DATABASE_SSL_MODE`, `DATABASE_SSL_ROOT_CERT`, pool) nesta spec; `jwt` e `crypto` entram na 002; `ldap`, `oidc` e `s3` nas 004 e 005. Validadores implementam R2.3: em `prod`, recusa `DEBUG` ligado, TLS diferente de `verify-full` e senha de exemplo nas URLs do banco (as do `.env.example` e do compose, ou qualquer senha com "troque", "exemplo", "example" ou "changeme"). `load_settings()` converte os erros em mensagens que nomeiam a variável, sem ecoar o valor recebido.

## Banco (`core/db.py`)
- `create_async_engine` com asyncpg, `pool_pre_ping`, contexto SSL com `verify-full` fora de `dev`.
- Dependência `get_session()` abre `AsyncSession`; casos de uso usam `async with session.begin()`.
- Alembic com `env.py` assíncrono; migração `0001_base` cria `audit_log`, função e trigger de imutabilidade, e o papel de banco `sgs_app` com `INSERT, SELECT` em `audit_log`.

## Erros (`core/errors.py`)
Hierarquia `AppError(status, type, title)` → `NotFound`, `Forbidden`, `Conflict`, `DomainValidationError`. Handlers para `AppError`, `RequestValidationError` (traduz mensagens do Pydantic para português) e `Exception`.

## Auditoria (`modules/audit`)
- `domain/`: `AuditEntry` e cálculo do hash canônico (JSON ordenado, sem espaços).
- `application/registrar.py`: busca o último hash com `SELECT ... FOR UPDATE` em uma linha de controle (`audit_chain_head`) para serializar o encadeamento.
- `infrastructure/`: repositório SQLAlchemy.

## Docker
`docker/compose.yml` com serviços `api`, `db` (postgres:17) e `proxy` (Caddy com TLS interno). Os serviços `ldap` (OpenLDAP com seed LDIF), `keycloak` (26.x, realm importado de `docker/keycloak/realm-sgs.json`) e `s3` (SeaweedFS) entram no compose nas specs 004 (T8) e 005 (T8). Override `compose.test.yml` para CI.

## CI
Ver `.github/workflows/ci.yml` (modelo já incluso neste pacote).

## Estratégia de testes
- Unidade: hash da auditoria, validadores de config.
- Integração (testcontainers): trigger impede UPDATE/DELETE; `/health/ready` com banco parado retorna 503.
- Contrato: schemathesis sobre `/openapi.json`.
