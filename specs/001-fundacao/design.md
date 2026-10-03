# 001 · Fundação da API · Design

- Status: Rascunho

## Visão geral
Projeto `sgs-api` gerenciado com `uv`, código em `src/sgs_api`, testes em `tests/`. O app é criado por uma fábrica `create_app(settings)` para permitir testes com configurações diferentes.

## Estrutura
Ver `steering/structure.md`. Nesta spec nascem: `core/config.py`, `core/db.py`, `core/errors.py`, `core/logging.py`, `core/security_headers.py`, `modules/audit/`, `migrations/`, `docker/`, `.github/workflows/ci.yml`.

## Configuração (`core/config.py`)
`Settings(BaseSettings)` com grupos: `app` (env, cors_origins), `db` (url, ssl_mode, pool), `jwt` (chaves, ttl), `crypto` (chaves de campo versionadas), `ldap`, `oidc`, `s3`. Validadores implementam R2.3.

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
`docker/compose.yml` com serviços `api`, `db` (postgres:17), `ldap` (OpenLDAP com seed LDIF), `keycloak` (26.x, realm importado de `docker/keycloak/realm-sgs.json`), `s3` (SeaweedFS), `proxy` (Caddy com TLS interno). Override `compose.test.yml` para CI.

## CI
Ver `.github/workflows/ci.yml` (modelo já incluso neste pacote).

## Estratégia de testes
- Unidade: hash da auditoria, validadores de config.
- Integração (testcontainers): trigger impede UPDATE/DELETE; `/health/ready` com banco parado retorna 503.
- Contrato: schemathesis sobre `/openapi.json`.
