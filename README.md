# sgs-api · Arquitetura inicial do backend

API da Plataforma de Governança de Dados de Saúde · Secretaria de Saúde do Recife · Grupo 01 (CESAR School, CS018).

Documentação, specs e steering vêm primeiro; o código segue as specs aprovadas (spec-driven development).

## Subir o ambiente (Docker)
Pré-requisito: Docker 26 ou mais novo, com Compose v2 (o compose monta partes de um volume com `subpath`). O compose sobe a API, o PostgreSQL 17 com TLS e um proxy TLS (Caddy). LDAP, Keycloak e S3 local entram nas specs 004 e 005.

```bash
mkdir -p secrets
uv run python -m src.tools.jwt_keys --output secrets/jwt-keys.json   # uma vez: chave JWT de dev
docker compose -f docker/compose.yml up -d --build --wait
curl -k https://localhost/health/ready      # {"status":"ok"}
```

- A API assina os access tokens (ES256) com a chave de `secrets/jwt-keys.json`, montada no container e lida por `JWT_PRIVATE_KEYS_FILE`; sem ela, não sobe. O arquivo é segredo e fica fora do Git. Formato e rotação: `src/tools/jwt_keys.py` e `.env.example`.
- Em `dev`, a API aplica as migrações na subida. Ela conecta como `sgs_api`, membro do papel `sgs_app`, que só insere e lê a trilha de auditoria; as migrações usam o dono do banco, `sgs`.
- O log do banco (`db_change_log`, spec 011) é particionado por mês, e as migrações criam as partições do mês atual até 12 meses à frente. Para estender o horizonte, rode no container o comando de administração, que conecta com `DATABASE_MIGRATION_URL`: `docker compose -f docker/compose.yml exec api sgs-admin banco particoes --meses 12`. Mês que já tem registros na partição DEFAULT é pulado, com aviso (spec 011, R6.6).
- As senhas do compose são de desenvolvimento; a API recusa iniciar com elas em `prod`.
- A API (e as migrações) conecta ao PostgreSQL por TLS em `verify-full`: confere o certificado e o nome `db` (spec 011, R10.3). Na subida, o serviço `db-certs` gera no volume `db-certs`, se faltarem, uma CA de desenvolvimento e o certificado do servidor; a chave da CA é descartada, e nenhuma chave ou certificado vai para o Git. O banco recusa conexão pela rede sem TLS (`docker/postgres/pg_hba.conf`). A primeira subida precisa de internet (o `db-certs` instala o `openssl`). Para gerar certificados novos, apague o volume: `docker compose -f docker/compose.yml down -v` (apaga também o banco). Para um `psql`, use o socket local: `docker compose -f docker/compose.yml exec db psql -U sgs sgs`.
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

Para o merge ficar bloqueado quando algo falha (spec 001, R7.2), a `main` é protegida por dois rulesets do repositório (Settings → Rules → Rulesets), conforme o [ADR-0008](docs/adr/0008-merge-admin-com-ci-obrigatorio.md).

O ruleset "main protegida (spec 001, R7.2)":
- só aceita mudanças por pull request;
- exige os checks `quality` e `compose-smoke` verdes, com a branch atualizada;
- bloqueia force-push e exclusão da branch.

O ruleset "revisão humana (ADR-0008)" exige 1 aprovação, descartada quando chegam commits novos. O administrador do repositório pode dispensá-la ao fazer merge de um PR (`gh pr merge <n> --admin`).

**Exceção provisória (desde 06/11/2026):** o GitHub Actions está bloqueado, então o administrador também pode fazer merge sem os checks, desde que o `make check` tenha passado localmente e o resultado esteja registrado no PR. A exceção sai quando o CI voltar ou a nova esteira entrar (ADR-0008).

A regra foi testada em 03/10/2026 numa branch descartável: um PR com lint quebrado falhou no CI e o merge foi recusado ("the base branch policy prohibits the merge"). Na máquina de cada um, o hook `no-commit-to-branch` do pre-commit também recusa commits feitos direto na `main`.

## Comece por aqui
| Documento | Para quê |
|---|---|
| [docs/research/01-pesquisa-stack-backend.md](docs/research/01-pesquisa-stack-backend.md) | Pesquisa da stack: FastAPI, auth, RBAC, LDAP, OIDC, S3, ferramentas |
| [docs/architecture/arquitetura-conceitual.md](docs/architecture/arquitetura-conceitual.md) | Papéis, recursos, matriz de permissões, componentes, fluxos, rotas |
| [docs/architecture/modelo-dados.md](docs/architecture/modelo-dados.md) | Tabelas e relacionamentos |
| [docs/adr/](docs/adr/) | Decisões arquiteturais (ADR-0001 a 0009) |
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
