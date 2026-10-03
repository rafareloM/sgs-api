# Steering · Tecnologia

## Stack (fixada; mudanças exigem ADR)
| Item | Versão |
|---|---|
| Python | 3.13 |
| FastAPI | 0.142.x |
| Pydantic / pydantic-settings | 2.13.x / 2.15.x |
| SQLAlchemy (async) + asyncpg | 2.1.x + 0.31.x |
| Alembic | 1.20.x |
| PostgreSQL | 17 |
| PyJWT[crypto] | 2.15.x (ES256) |
| pwdlib[argon2] | 0.3.x |
| pyotp | 2.10.x |
| Authlib | 1.8.x |
| ldap3 | 2.9.1 |
| boto3 | 1.43.x |
| cryptography | 50.x |
| structlog | 26.x |
| openpyxl | 3.1.x |
| Uvicorn | 0.54.x (ADR-0007) |
| slowapi | 0.1.x (ADR-0007) |

Ferramentas: uv, ruff, mypy, import-linter, pytest (+ pytest-asyncio, pytest-cov, httpx, testcontainers, moto, hypothesis, schemathesis), bandit, pip-audit, pre-commit. O pytest-cov entrou pelo ADR-0007.

Bibliotecas **proibidas** sem ADR: python-jose, passlib, fastapi-users, SQLModel, MinIO SDK, qualquer ORM além do SQLAlchemy.

## Convenções de código
- Tipagem completa; `mypy --strict` em `domain` e `application`.
- `async def` nas rotas e casos de uso. Bibliotecas bloqueantes (ldap3, boto3, openpyxl) só dentro de adaptadores, via `anyio.to_thread.run_sync`.
- Schemas Pydantic de entrada e saída separados dos modelos SQLAlchemy. Nunca devolver modelo ORM direto.
- Erros de negócio levantam subclasses de `AppError`; nada de `HTTPException` fora da camada `api`.
- Datas sempre `datetime` com timezone (UTC no banco).
- IDs: UUID v7.
- Configuração só via `Settings`; nunca `os.environ` espalhado.

## Comandos
| Comando | O que faz |
|---|---|
| `make check` | `ruff check`, `ruff format --check`, `mypy`, `lint-imports`, `pytest -m "not slow"` |
| `make test-all` | todos os testes, inclusive integração com Docker |
| `make openapi` | exporta `contracts/openapi.yaml` |
| `make migrate m="mensagem"` | gera migração Alembic (revisar à mão) |
| `make up` / `make down` | sobe/derruba o compose |

## Ambientes
`APP_ENV=dev|test|prod`. Mesmo compose com overrides. Em `prod`: TLS obrigatório até o banco, sem docs OpenAPI, sem chaves de exemplo, S3 só com AssumeRole.
