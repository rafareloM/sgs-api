# Registros de decisão (ADR)

Cada decisão arquitetural relevante vira um arquivo curto e imutável. Para mudar uma decisão, crie um novo ADR que a substitua e marque o antigo como "Substituído por".

| ADR | Título | Status |
|---|---|---|
| [0001](0001-fastapi-como-backend.md) | FastAPI/Python como backend | Proposto |
| [0002](0002-monolito-modular.md) | Monólito modular com camadas | Proposto |
| [0003](0003-identidade-federada-tokens-proprios.md) | Identidade federada (LDAP/OIDC) com tokens próprios | Proposto |
| [0004](0004-rbac-proprio-com-escopo.md) | RBAC próprio com escopo | Proposto |
| [0005](0005-exportacao-relatorios-s3.md) | Exportação de relatórios para S3 com STS | Proposto |
| [0006](0006-sdd-e-esteira-agentica.md) | Spec-driven development e esteira agêntica | Proposto |
| [0007](0007-dependencias-complementares.md) | Dependências complementares da stack (Uvicorn, slowapi, pytest-cov) | Aceito |

Modelo: `0000-modelo.md`.
