# sgs-api · Arquitetura inicial do backend

API da Plataforma de Governança de Dados de Saúde · Secretaria de Saúde do Recife · Grupo 01 (CESAR School, CS018).

Documentação, specs e steering vêm primeiro; o código segue as specs aprovadas (spec-driven development).

## Subir o ambiente (Docker)
Pré-requisito: Docker com Compose v2. O compose sobe a API, o PostgreSQL 17 e um proxy TLS (Caddy). LDAP, Keycloak e S3 local entram nas specs 004 e 005.

```bash
docker compose -f docker/compose.yml up -d --build --wait
curl -k https://localhost/health/ready      # {"status":"ok"}
```

- Em `dev`, a API aplica as migrações na subida. Ela conecta como `sgs_api`, membro do papel `sgs_app`, que só insere e lê a trilha de auditoria; as migrações usam o dono do banco, `sgs`.
- As senhas do compose são de desenvolvimento; a API recusa iniciar com elas em `prod`.
- O certificado vem da CA interna do Caddy, por isso o `-k`. Para confiar na CA em vez disso (`secrets/` fica fora do Git):

  ```bash
  mkdir -p secrets
  docker compose -f docker/compose.yml cp proxy:/data/caddy/pki/authorities/local/root.crt secrets/caddy-root.crt
  curl --cacert secrets/caddy-root.crt https://localhost/health/ready
  ```
  No Windows, o `curl.exe` (Schannel) precisa também de `--ssl-no-revoke`, porque a CA local não publica lista de revogação.
- Documentação interativa (só em `dev` e `test`): https://localhost/docs.
- Parar: `docker compose -f docker/compose.yml down` (com `-v`, apaga também o banco).

## Desenvolvimento
Pré-requisitos: [uv](https://docs.astral.sh/uv/), GNU Make e Docker (os testes de integração sobem um PostgreSQL com testcontainers). No Windows, o Make vem com `winget install --id ezwinports.make -e`.

```bash
uv sync                    # Python 3.13 e dependências, travadas pelo uv.lock
uv run pre-commit install  # verificações antes de cada commit
make check                 # lint, formatação, tipos, camadas e testes
make openapi               # regenera contracts/openapi.yaml depois de mudar rotas
```

Para rodar os testes num PostgreSQL já em execução, em vez do testcontainers, defina `SGS_TEST_DATABASE_URL` com o superusuário de um servidor descartável: os testes criam e apagam bancos nele.

## CI e proteção da `main`
O workflow `.github/workflows/ci.yml` roda em todo PR: dependências travadas, ruff, mypy, import-linter, testes com cobertura (PostgreSQL de serviço), contrato OpenAPI, bandit e pip-audit (job `quality`); depois sobe o compose e chama `/health/ready` pelo proxy TLS (job `compose-smoke`).

Para o merge ficar bloqueado quando algo falha (spec 001, R7.2), a `main` precisa de uma regra de proteção no GitHub (Settings → Branches):
- exigir pull request com 1 aprovação, descartando aprovações antigas quando chegam commits novos;
- exigir os checks `quality` e `compose-smoke` verdes, com a branch atualizada;
- bloquear push direto e force-push, valendo também para administradores.

Em repositório privado, a proteção de branch exige plano Pro ou Team (o GitHub Student Developer Pack inclui o Pro); em repositório público, está disponível no plano gratuito.

## Comece por aqui
| Documento | Para quê |
|---|---|
| [docs/research/01-pesquisa-stack-backend.md](docs/research/01-pesquisa-stack-backend.md) | Pesquisa da stack: FastAPI, auth, RBAC, LDAP, OIDC, S3, ferramentas |
| [docs/architecture/arquitetura-conceitual.md](docs/architecture/arquitetura-conceitual.md) | Papéis, recursos, matriz de permissões, componentes, fluxos, rotas |
| [docs/architecture/modelo-dados.md](docs/architecture/modelo-dados.md) | Tabelas e relacionamentos |
| [docs/adr/](docs/adr/) | Decisões arquiteturais (ADR-0001 a 0007) |
| [specs/](specs/) | Specs SDD 001 a 010 (requisitos EARS, design, tarefas), rastreabilidade e calendário |
| [AGENTS.md](AGENTS.md), [CLAUDE.md](CLAUDE.md), [steering/](steering/) | Contexto e regras para agentes de código |
| [.claude/commands/](.claude/commands/) | Comandos do fluxo SDD no Claude Code |
| [.github/](.github/) | CI e template de PR |

## Ordem de implementação sugerida
Ver o calendário em [specs/README.md](specs/README.md#ordem-e-calendário-sugeridos): fundação e login primeiro, depois RBAC e cadastro, validação e dados de demonstração, histórico e dashboard, e por fim LDAP/OIDC e exportação S3.

## Pendências para o grupo
- Confirmar FastAPI e atualizar o Documento de Arquitetura da Atividade 5, que ainda diz Node.js (ADR-0001).
- Aprovar ou ajustar a matriz de papéis × permissões.
- Definir o dono humano de cada spec.
