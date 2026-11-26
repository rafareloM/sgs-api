# Implementação das specs 004 e 005 em três frentes

- Data: 24/11/2026
- Para quem: integrantes do Grupo 01 que vão implementar uma frente, com ou sem agente de código.
- Specs: [004 · Diretório LDAP e OIDC](../../specs/004-diretorio-ldap-oidc/) e [005 · Exportação de relatórios para S3](../../specs/005-exportacao-relatorios-s3/). Requisitos, design e tarefas estão aprovados (G1, G2 e G3 do Rafael, em 24/11/2026).
- Donos das specs: Vinicius (ViniciusVbm) e Rafael (rafareloM). Dúvida de escopo ou de requisito vai para eles.

| Frente | Guia | O que entrega |
|---|---|---|
| A · Diretório LDAP | [frente-a-diretorio-ldap.md](frente-a-diretorio-ldap.md) | Porte da 003/T8, tabelas do diretório, sincronização, login LDAP, agendamento |
| B · OIDC e laboratório | [frente-b-oidc-laboratorio.md](frente-b-oidc-laboratorio.md) | Keycloak e `slapd` no compose, login OIDC, botão no front, assinatura dos relatórios, demonstração ponta a ponta da 004 |
| C · Relatórios | [frente-c-relatorios.md](frente-c-relatorios.md) | Exportação CSV/XLSX, envio ao S3 com STS, download por URL pré-assinada, SeaweedFS no compose |

**Com agentes, uma pessoa por frente:** [agentes.md](agentes.md) traz a skill `/frente` (prepara a máquina e roda cada tarefa), as permissões do Claude Code e o que revisar antes de integrar.

## Regras que não mudam
1. **A spec é a fonte da verdade** (`AGENTS.md`). Código que diverge da spec é bug. Se a spec estiver errada, pare e fale com os donos: a mudança vai primeiro para a spec (`Em revisão`), depois para o código.
2. **Uma tarefa por vez, com teste antes** (TDD). O teste cita o critério na docstring (`"""004/R1.7"""`), e a tarefa só fica `[x]` com o teste de "Pronto quando" verde e o `make check` verde.
3. **Ninguém marca nada como `Aprovado`.** Aprovação é só dos donos.
4. **Toda rota declara a permissão** (`require("recurso:acao")`) ou entra na lista de públicas com justificativa.
5. **A auditoria vai na mesma transação** do caso de uso.
6. **O domínio não importa** FastAPI, SQLAlchemy, boto3, ldap3 nem Authlib (o `lint-imports` confere).
7. **Mudou rota?** Rode `make openapi` e versione o contrato.
8. **Nenhum segredo, token, senha ou URL pré-assinada** em log, exceção, resposta ou commit (`steering/security.md`).

## Antes de começar (uns 40 minutos)
Leia, nesta ordem:
1. `AGENTS.md`;
2. `steering/sdd-workflow.md`, `steering/security.md`, `steering/testing.md`;
3. o `design.md` e o `tasks.md` da spec de cada tarefa da sua frente;
4. o guia da sua frente.

Prepare a máquina (com o Claude Code, a skill `/frente` faz isto: [agentes.md](agentes.md#a-skill-frente)):
- Docker 26 ou mais novo (Compose v2), [uv](https://docs.astral.sh/uv/), GNU Make e git com acesso ao `rafareloM/sgs-api`.
- Siga o README § Desenvolvimento e § Subir o ambiente:

  ```bash
  uv sync
  uv run pre-commit install
  mkdir -p secrets
  uv run python -m src.tools.jwt_keys --output secrets/jwt-keys.json
  uv run python -m src.tools.crypto_keys --output secrets/crypto-keys.json
  printf 'SGS_BORDA_SUBNET=10.231.1.0/28\nSGS_BORDA_PROXY_IP=10.231.1.14\n' > docker/.env
  make check          # precisa do Docker: os testes de integração sobem um PostgreSQL
  ```

- O `make check` tem de passar no *worktree* da frente (§ Ramos e *worktrees*), que sai do `feat/004-005`, antes de você mudar qualquer coisa. Se não passar, o problema é da máquina, não da tarefa.
- **Agente de código.** Rode o agente (Claude Code ou outro) num terminal da máquina, dentro do *worktree* da frente, com acesso ao Docker. Um editor em sandbox (por exemplo, o VS Code em Flatpak) esconde o Docker e o `uv`, e os testes de integração não rodam.

## Ramos e *worktrees*
- A `main` recebe só PR (ADR-0008).
- O ramo de integração é `feat/004-005`, criado pelo Rafael a partir da `main`, já com a T0 (dependências novas e o erro 503).
- Cada frente trabalha num *worktree* próprio:

```bash
git fetch origin
git worktree add ../sgs-frente-a -b frente/a origin/feat/004-005   # troque "a" pela sua frente
cd ../sgs-frente-a
uv sync
```

Cada pessoa roda a sua frente na própria máquina, e os valores padrão servem. Se duas frentes rodarem na mesma máquina, o `docker/.env` de cada *worktree* usa uma subnet própria (por exemplo, `10.231.2.0/28` na frente B e `10.231.3.0/28` na C). As portas do proxy também mudam (`SGS_HTTP_PORT`, `SGS_HTTPS_PORT` e as URLs públicas, ver o guia da frente B). Assim, as duas sobem o compose ao mesmo tempo.

## Ciclo de uma tarefa
1. **Confira se pode começar.** As tarefas de "Bloqueada por" já estão integradas no `feat/004-005` (`git log origin/feat/004-005`).
2. **Atualize** o ramo: `git fetch origin && git rebase origin/feat/004-005`.
3. **Leia** a tarefa no `tasks.md`, as seções do design que o guia da frente aponta e os critérios `Rx.y` da tarefa no `requirements.md`.
4. **Teste primeiro.** Escreva o teste de "Pronto quando" e veja-o falhar pelo motivo certo.
5. **Implemente** o mínimo para o teste passar. Depois, os testes negativos (401, 403, 422) das rotas novas.
6. **Rode** `make check`, e `make openapi` se a rota mudou.
7. **Marque a tarefa:** `[x]` no `tasks.md`, com uma linha "Concluída em DD/MM/AAAA (`make check` verde). Prova: `<arquivo de teste>`", como nas specs anteriores.
8. **Faça o commit** no formato `tipo(módulo): descrição (NNN/Tn)`, por exemplo `feat(identity): login por LDAP (004/T5)`. Se um agente ajudou, termine com o trailer `Co-Authored-By` do agente. Isso alimenta o "Registro de uso de IA" da entrega final.
9. **Integre:**

   ```bash
   git fetch origin && git rebase origin/feat/004-005 && make check
   git push origin HEAD:feat/004-005
   ```

   Se o push for recusado porque outra frente integrou antes, repita a linha.
10. **Avise** no canal do grupo: "Integrada: 004/T5 (`<hash>`)". O guia de cada frente diz quais avisos destravam as outras.

Com o Claude Code, o passo 3 em diante é o comando do repositório `/spec-implementar <spec> <Tn>`, por exemplo `/spec-implementar 004-diretorio-ldap-oidc T5`. Ele confere a aprovação, escreve o teste primeiro, implementa, roda o `make check` e faz o commit. Leia o diff antes de integrar. Use um contexto limpo (`/clear`) para cada tarefa: a tarefa e o design bastam.

## Regras de integração
O texto completo está em `specs/004-diretorio-ldap-oidc/tasks.md` § Frentes de trabalho. O essencial:
- **Migrações.** A 004/T1 cria `0004_diretorio` e a 005/T1 cria `0005_relatorios`. Quem integrar por último aponta o seu `down_revision` para a outra. `uv run alembic heads` tem de mostrar uma cabeça só.
- **`pyproject.toml` e `uv.lock`** só mudam na T0. Precisou de uma biblioteca nova? Pare e fale com os donos: a stack é fixada por ADR.
- **`src/core/config.py`.** Cada área tem o seu bloco de campos e o seu método `_<área>_problems()`.
- **`docker/compose.yml`, `Caddyfile`, `.env.example` e `README.md`** ficam com a frente B até a 004/T13 entrar. Depois, a 005/T8 acrescenta o S3.
- **Fora da sua frente.** Se a tarefa pedir mudança num arquivo que o guia não cita, avise antes, para não pisar em outra frente.

## Pontos de encontro
| Quem espera | Precisa de | Aviso que destrava |
|---|---|---|
| B · 004/T7 | A · 003/T8 e 004/T1 | "Integrada: 003/T8" e "Integrada: 004/T1" |
| C · 005/T5 | B · 005/T9 | "Integrada: 005/T9" |
| C · 005/T8 | B · 004/T8 | "Integrada: 004/T8" |
| B · 004/T14 | A · 004/T4, T5 e T11 | os três avisos |

Esperando? Adiante o que não depende do bloqueio, como o roteiro da demonstração ou os testes negativos. Não implemente o código de outra frente.

## Quando parar e chamar os donos
- Uma das conferências de risco falhou:
  - `iss` diferente no Keycloak (004/T8);
  - SeaweedFS sem SSE (005/T10 ou T8);
  - `ldap3` sem conferir o nome do servidor (004/T11).
- O teste de "Pronto quando" só passa mudando um requisito ou uma decisão do design.
- A tarefa vai passar muito das ~300 linhas de diff. Ela pode ser dividida, mas a divisão é registrada no `tasks.md` pelos donos.
- Precisou de biblioteca, permissão, papel ou rota que o design não prevê.

## No fim
- Quando todas as tarefas de uma spec estiverem `[x]`, o Rafael abre o PR `feat/004-005` → `main` daquela spec. O PR segue o template e passa por `/spec-revisar` e pelo CI, e o merge segue o ADR-0008.
- Depois da entrega, uma retrospectiva curta: o que travou, o que faltou no ambiente, o que vira regra ou verificação automática.
