# Steering · Estrutura

```
.
├── AGENTS.md / CLAUDE.md
├── steering/                 # contexto permanente para agentes
├── specs/NNN-nome/           # requirements.md, design.md, tasks.md
├── docs/
│   ├── architecture/         # arquitetura conceitual, modelo de dados
│   ├── adr/                  # decisões
│   └── research/             # pesquisa e revisão de critérios
├── contracts/openapi.yaml    # contrato gerado e versionado
├── src/                      # código da API, direto aqui; o pacote importável é `src`
│   ├── main.py               # create_app() e raiz de composição
│   ├── core/                 # config, db, errors, logging, crypto, security_headers
│   ├── tools/                # exportação do OpenAPI e comandos de administração
│   └── modules/
│       ├── identity/         # usuários, grupos, login, 2FA, tokens, LDAP, OIDC
│       ├── access/           # RBAC: papéis, permissões, escopo, require()
│       ├── registry/         # unidades, equipamentos, serviços, validação
│       ├── audit/            # trilha imutável
│       ├── reports/          # geração e exportação S3
│       └── dashboard/        # agregados
│           (cada módulo: api/ application/ domain/ infrastructure/)
├── migrations/               # Alembic
├── tests/
│   ├── unit/<módulo>/
│   ├── integration/<módulo>/
│   ├── architecture/
│   └── e2e/                  # marcador slow, usa o compose
├── docker/                   # compose.yml, ldap/, keycloak/, caddy/
└── .github/                  # CI e template de PR
```

## Regras de dependência (import-linter)
- `modules.*.domain` → só stdlib, pydantic e `core.errors`.
- `modules.*.application` → `domain` do próprio módulo e `application` de outros módulos.
- `modules.*.api` → `application` do próprio módulo, `access.api.deps`, `core`.
- `modules.*.infrastructure` → `domain` do próprio módulo, `core`, bibliotecas externas.
- Nenhum módulo importa `infrastructure` de outro.

## Nomes
- Rotas em português, plural: `/unidades`, `/relatorios`, `/admin/atribuicoes`.
- Tabelas em inglês, plural: `health_units`, `report_jobs`.
- Permissões `recurso:acao` em português: `unidade:update`.
- Ações de auditoria `recurso.verbo_no_passado`: `unidade.atualizada`, `auth.login`.
