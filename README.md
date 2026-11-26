# sgs-api · API de Governança de Dados de Saúde

API da Plataforma de Governança de Dados de Saúde · Secretaria de Saúde do Recife · Grupo 01 (CESAR School, CS018).

Documentação, specs e steering vêm primeiro; o código segue as specs aprovadas (spec-driven development).

**O que a API faz:**
- cadastro único de unidades, equipamentos e serviços de saúde, com busca, escopo por papel, controle de concorrência (`If-Match`) e auditoria;
- login com senha (Argon2id) e TOTP, tokens ES256, refresh rotativo e RBAC com escopo;
- trilha de auditoria imutável e verificável, mais o log do banco por trigger;
- dashboard com as consultas da disciplina de Banco de Dados (anti join, full outer join, subconsultas, views, procedures, triggers) e indicadores.

**Documentação atual oficial** (entrega final de Banco de Dados, Etapas 01 a 06):
- este README;
- a matriz de conformidade [docs/banco/07-matriz-conformidade.md](docs/banco/07-matriz-conformidade.md), com cada requisito → objeto no banco, rota, tela e teste;
- o roteiro de demonstração [docs/banco/08-roteiro-demonstracao.md](docs/banco/08-roteiro-demonstracao.md).

Visão geral para o grupo e os professores: o [relatório geral do projeto na Etapa 06](docs/relatorios/RELATORIO_GERAL_PROJETO_ETAPA06.md), que resume banco, aplicação, segurança, testes e pendências e remete à matriz e ao roteiro.

Os relatórios de 09/11 e 10/11/2026 são **registros históricos**, preservados sem alteração. Eles não refletem a interface da Etapa 06 nem a aprovação do cenário D das 30 tuplas (ver § Registros históricos).

## Subir o ambiente (Docker)
Pré-requisito: Docker 26 ou mais novo, com Compose v2 (o compose monta partes de um volume com `subpath`). O compose sobe a API, o PostgreSQL 17 com TLS, um proxy TLS (Caddy), o Keycloak e o LDAP de laboratório (spec 004) e o S3 local, SeaweedFS (spec 005).

```bash
mkdir -p secrets
uv run python -m src.tools.jwt_keys --output secrets/jwt-keys.json   # uma vez: chave JWT de dev
uv run python -m src.tools.crypto_keys --output secrets/crypto-keys.json   # uma vez: chave de cifra
uv run python -m src.tools.jwt_keys --kid rel-$(date +%F) --output secrets/report-keys.json  # uma vez: relatórios
uv run python -m src.tools.s3_sse_key --output secrets/s3-security.toml  # uma vez: SSE do S3 local
printf 'SGS_BORDA_SUBNET=10.231.1.0/28\nSGS_BORDA_PROXY_IP=10.231.1.14\n' > docker/.env  # uma vez
docker compose -f docker/compose.yml up -d --build --wait
curl -k https://localhost/health/ready      # {"status":"ok"}
```

- A API assina os access tokens (ES256) com a chave de `secrets/jwt-keys.json`, montada no container e lida por `JWT_PRIVATE_KEYS_FILE`; sem ela, não sobe. O arquivo é segredo e fica fora do Git. Formato e rotação: `src/tools/jwt_keys.py` e `.env.example`.
- **Chave de assinatura dos relatórios (spec 005, R5).** Ela é gerada pela mesma ferramenta, mas é outra chave, com outro `kid`: `uv run python -m src.tools.jwt_keys --kid rel-$(date +%F) --output secrets/report-keys.json`. Rode esse comando só se o arquivo ainda não existir: ele sobrescreve o arquivo e apaga as chaves anteriores, que ainda conferem os relatórios assinados antes (R5.5). Para trocar a chave, siga a rotação de [docs/operacao/verificar-relatorio.md](docs/operacao/verificar-relatorio.md#rotação-r55). A API lê o arquivo por `REPORT_SIGNING_KEYS_FILE` (ou o JSON em `REPORT_SIGNING_KEYS`) e publica as chaves públicas em `/.well-known/relatorios-jwks.json`. Ela recusa iniciar se um `kid` ou uma chave coincidir com as chaves JWT. Sem a chave, nada é assinado e a exportação fica desligada (503). O compose monta o arquivo como segredo na API. Verificação fora da API e rotação: [docs/operacao/verificar-relatorio.md](docs/operacao/verificar-relatorio.md).
- Em `dev`, a API aplica as migrações na subida. Ela conecta como `sgs_api`, membro do papel `sgs_app`, que só insere e lê a trilha de auditoria; as migrações usam o dono do banco, `sgs`.
- O log do banco (`db_change_log`, spec 011) é particionado por mês, e as migrações criam as partições do mês atual até 12 meses à frente. Para estender o horizonte, rode no container o comando de administração, que conecta com `DATABASE_MIGRATION_URL`: `docker compose -f docker/compose.yml exec api sgs-admin banco particoes --meses 12`. Mês que já tem registros na partição DEFAULT é pulado, com aviso (spec 011, R6.6).
- **Credenciais de desenvolvimento.** As senhas do compose (`docker/compose.yml`) e do script de inicialização do banco (`docker/postgres/init/01-usuario-app.sql`) servem **só para ambientes locais e descartáveis**. Não as use em produção nem em ambientes compartilhados. Em ambientes reais, use credenciais fortes e únicas, fornecidas por um mecanismo seguro de configuração (variáveis de ambiente ou gerenciador de segredos), nunca versionadas. Com `APP_ENV=prod`, a API **recusa iniciar** com senha de exemplo, chave de cifra de exemplo, `DEBUG` ligado ou TLS do banco diferente de `verify-full` (`src/core/config.py`).
- **Chaves reais** (JWT, cifra e relatórios) ficam em `secrets/`, que está no `.gitignore`: não as publique nem as copie para o repositório.
- A API (e as migrações) conecta ao PostgreSQL por TLS em `verify-full`: confere o certificado e o nome `db` (spec 011, R10.3). Na subida, o serviço `db-certs` gera no volume `db-certs`, se faltarem, uma CA de desenvolvimento e o certificado do servidor; a chave da CA é descartada, e nenhuma chave ou certificado vai para o Git. O banco recusa conexão pela rede sem TLS (`docker/postgres/pg_hba.conf`). A primeira subida precisa de internet (o `db-certs` instala o `openssl`). Para gerar certificados novos, apague o volume: `docker compose -f docker/compose.yml down -v` (apaga também o banco). Para um `psql`, use o socket local: `docker compose -f docker/compose.yml exec db psql -U sgs sgs`.
- O certificado vem da CA interna do Caddy, por isso o `-k`. Para confiar na CA em vez disso (`secrets/` fica fora do Git):

  ```bash
  mkdir -p secrets
  docker compose -f docker/compose.yml cp proxy:/data/caddy/pki/authorities/local/root.crt secrets/caddy-root.crt
  curl --cacert secrets/caddy-root.crt https://localhost/health/ready
  ```
  No Windows, o `curl.exe` (Schannel) precisa também de `--ssl-no-revoke`, porque a CA local não publica lista de revogação.
- Documentação interativa (só em `dev` e `test`): hoje **não** abre pelo proxy, porque desde a spec 012 (T1) o `/docs` cai no front. Use o contorno do [guia de execução](docs/GUIA_EXECUCAO_LOCAL_SGS_RECIFE.md) § 1.6 ou o contrato [contracts/openapi.yaml](contracts/openapi.yaml). Achado A1 do [relatório de implementação](docs/RELATORIO_IMPLEMENTACAO_SGS_RECIFE.md).
- **Provedor OIDC de laboratório (spec 004, R5.2).** O Keycloak sobe com o realm `sgs` (`docker/keycloak/realm-sgs.json`) e responde em `https://keycloak.localhost`, pelo mesmo Caddy (os navegadores levam `*.localhost` à própria máquina; no `curl`, use `--resolve keycloak.localhost:443:127.0.0.1`). A API fala com ele direto, em `https://keycloak:8443`, pela rede interna `integracoes`, e não depende dele para ficar saudável. Ele deixa o `--wait` da primeira subida uns 30 a 60 s mais longo e usa perto de 1 GB de memória.
  - Usuários de exemplo, um por papel da spec 003, cada um no seu grupo (claim `groups`): `oidc.admin.ti`, `oidc.gestor.dados`, `oidc.coord.tecnico`, `oidc.tecnico.ds4` (grupo `oidc-tecnico-ds-iv`), `oidc.gestor.unidade` (`oidc-gestor-unidade-cnes-1000002`), `oidc.diretoria` e `oidc.auditor`. Senha de todos: `sgs-lab-exemplo-usuario`.
  - Cliente `sgs-api`: confidencial, PKCE S256, segredo `sgs-lab-exemplo-oidc`. Console em `https://keycloak.localhost/admin`, usuário `admin`, senha `sgs-lab-exemplo-admin`.
  - Essas senhas são fixas, versionadas e só do laboratório (D004-15). O marcador `exemplo` faz a API recusá-las em `prod` (004/R5.4).
  - O serviço `servicos-certs` gera no volume de mesmo nome, como o `db-certs` faz para o banco, uma CA de laboratório e os certificados de `ldap`, `keycloak` e `s3`. A chave da CA é descartada.
- **Diretório LDAP de laboratório (spec 004, R5.1).** OpenLDAP (`docker/ldap/`) só com LDAPS, sem porta no host: a API chega a ele em `ldaps://ldap:636`, pela rede `integracoes`, conferindo o certificado pela CA de laboratório. A carga inicial (`docker/ldap/seed.ldif`) entra na primeira subida e fica no volume `ldap-data`; para voltar a ela, apague o volume (`down -v`).
  - Conta de serviço `cn=sgs-sync,ou=servicos,dc=recife,dc=pe,dc=gov,dc=br`, só leitura, senha `sgs-lab-exemplo-bind`.
  - Usuários de exemplo em `ou=pessoas`, um por papel da spec 003, cada um num grupo `groupOfNames` de `ou=grupos` cujo nome diz o papel e o escopo: `ldap.admin.ti` (`sgs-admin-ti`), `ldap.gestor.dados` (`sgs-gestor-dados`), `ldap.coord.tecnico` (`sgs-coord-tecnico-aps`), `ldap.tecnico.ds3` (`sgs-tecnico-ds3`), `ldap.gestor.unidade` (`sgs-gestor-unidade-cnes-1000003`), `ldap.diretoria` (`sgs-diretoria`) e `ldap.auditor` (`sgs-auditor`). Mais `ldap.temporario`, também em `sgs-tecnico-ds3`, para a demonstração da desativação. Senha de todos: `sgs-lab-exemplo-usuario`, guardada em `{SSHA}`.
  - Alterações no diretório, como o usuário do contêiner, pelo `ldapi` (o mesmo caminho da carga inicial): `docker compose -f docker/compose.yml exec ldap ldapdelete -Y EXTERNAL -H ldapi:/// uid=ldap.temporario,ou=pessoas,dc=recife,dc=pe,dc=gov,dc=br`.
  - Essas senhas também são fixas, versionadas e só do laboratório (D004-15), e a API as recusa em `prod` (004/R5.4).
- **S3 local de laboratório (spec 005, R6).** SeaweedFS 4.53 (`chrislusf/seaweedfs`, tag e digest fixos) com o S3 só em HTTPS, sem porta no host: a API envia em `https://s3:8333`, pela rede `integracoes`, conferindo o certificado pela CA de laboratório; o navegador baixa pelas URLs pré-assinadas em `https://s3.localhost`, pelo Caddy (R6.2). O `s3-init` cria o bucket `sgs-relatorios` e liga o versionamento, sem erro se já existirem.
  - A criptografia no servidor (`AES256`, conferida pela API em cada envio, R2.8) precisa da chave de `secrets/s3-security.toml` (`src.tools.s3_sse_key`), montada como segredo. Sem ela, o SeaweedFS recusa todo envio. Não gere outra depois: os objetos já gravados ficariam ilegíveis.
  - Identidade da API: `sgs-lab-exemplo` / `sgs-lab-exemplo-s3` (`docker/seaweedfs/s3.json`), só leitura, escrita e listagem no bucket. Chaves fixas, versionadas e só do laboratório: a API as recusa em `prod` (R2.9).
  - Roteiro da demonstração: [docs/operacao/demo-relatorios.md](docs/operacao/demo-relatorios.md).
- **Portas e endereços públicos.** Com `SGS_HTTPS_PORT` diferente de 443, ajuste junto, em `docker/.env`, `SGS_PUBLIC_URL`, `SGS_PUBLIC_KEYCLOAK_URL` e `SGS_PUBLIC_S3_URL` (padrões `https://localhost`, `https://keycloak.localhost` e `https://s3.localhost`). Elas alimentam ao mesmo tempo os serviços e a API (`OIDC_ISSUER`, `OIDC_REDIRECT_URI`, `FRONTEND_URL`, a origem padrão de `CORS_ORIGINS` e `S3_PUBLIC_ENDPOINT_URL`). Exemplo: `SGS_HTTPS_PORT=8443`, `SGS_PUBLIC_URL=https://localhost:8443`, `SGS_PUBLIC_KEYCLOAK_URL=https://keycloak.localhost:8443` e `SGS_PUBLIC_S3_URL=https://s3.localhost:8443`.
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

## Dados de demonstração e primeiro administrador
```bash
docker compose -f docker/compose.yml exec -e SGS_SEED_SENHA='senha-demo' api sgs-admin seed demo
docker compose -f docker/compose.yml exec -e SGS_SENHA_INICIAL='senha-longa' api \
  sgs-admin create-user --username admin --nome "Administrador"
```
Os valores `senha-demo` e `senha-longa` são **apenas ilustrativos**: escolha senhas próprias na hora de rodar e não as registre em arquivos versionados. O seed e esses usuários servem só para ambientes locais e descartáveis; o seed é idempotente e é recusado em prod. Detalhes em [docs/instalacao.md](docs/instalacao.md).

## Demonstração da interface (entrega final de Banco de Dados)
Com o ambiente no ar e o seed carregado, abra `https://localhost/` (ou a porta de `SGS_HTTPS_PORT`). Entre com um usuário do seed: a senha é a de `SGS_SEED_SENHA`, e o 2FA é cadastrado no primeiro acesso. O roteiro de cerca de 8 minutos está em [docs/banco/08-roteiro-demonstracao.md](docs/banco/08-roteiro-demonstracao.md), e a matriz requisito → tela → teste em [docs/banco/07-matriz-conformidade.md](docs/banco/07-matriz-conformidade.md).

| Tela | Caminho | Quem vê | O que mostra |
|---|---|---|---|
| Início | `#/inicio` | quem tem `dashboard:read` | totais e distribuições do resumo |
| Qualidade dos dados | `#/qualidade` | quem tem `dashboard:read` | indicadores (médias, %, tendência), gráficos e as consultas e views da disciplina, com filtros |
| Unidades | `#/unidades` | todos os papéis de negócio | lista com busca sem acento, filtros e paginação |
| Ficha da unidade | `#/unidade/{id}` | idem | dados, versão, serviços, histórico; editar e desativar (Gestor de Dados) |
| Cadastrar unidade | `#/nova` | Gestor de Dados | cadastro; abre a ficha nova |
| Tabelas de referência | `#/referencias` | Gestor de Dados | CRUD dos tipos de unidade, equipamento e serviço; cascata do código |
| Histórico geral | `#/historico` | Gestor de Dados e Auditor | trilha, log do banco (trigger) e partições (procedimento) |
| Verificação da cadeia | `#/cadeia` | Auditor | integridade da trilha de auditoria |

Testes da interface: `uv run pytest -m slow tests/e2e_front` (sobe um compose próprio e descartável, com portas alternativas).

## Comece por aqui
| Documento | Para quê |
|---|---|
| **Matriz de conformidade:** [docs/banco/07-matriz-conformidade.md](docs/banco/07-matriz-conformidade.md) | **Comece por esta.** Cada requisito acadêmico das Etapas 03 a 06 → objeto no banco, rota da API, tela e teste |
| **Roteiro de demonstração:** [docs/banco/08-roteiro-demonstracao.md](docs/banco/08-roteiro-demonstracao.md) | Apresentação de cerca de 8 minutos, com os usuários do seed, cuidados prévios e o que fazer se um passo falhar |
| **Relatório geral atual (Etapa 06):** [docs/relatorios/RELATORIO_GERAL_PROJETO_ETAPA06.md](docs/relatorios/RELATORIO_GERAL_PROJETO_ETAPA06.md) | Visão geral do projeto: banco de dados em detalhe, aplicação, segurança, testes, conformidade, pendências e como executar |
| [§ Demonstração da interface](#demonstração-da-interface-entrega-final-de-banco-de-dados) | Caminho de cada tela e quem a vê |
| [docs/instalacao.md](docs/instalacao.md) | Instalação, execução, variáveis de ambiente, Docker e testes |
| [docs/api/endpoints.md](docs/api/endpoints.md) · [docs/api/autenticacao.md](docs/api/autenticacao.md) | Os 55 endpoints com a permissão de cada um; fluxo de login para o front |
| [docs/banco/](docs/banco/) | Disciplina de Banco de Dados: minimundo, modelos, dicionário, objetos, 30 tuplas (cenário D, aprovado), prova dos índices, matriz de conformidade e roteiro de demonstração |
| [docs/governanca/](docs/governanca/) | Fornecedores, matriz e registro de riscos, ISO 38500, COBIT APO10, LGPD |
| [docs/frontend-integracao.md](docs/frontend-integracao.md) | Como o front (`frontend/app`, spec 012) usa a API |
| [docs/integration-audit/](docs/integration-audit/) | Auditoria das 15 branches e plano de consolidação (registro histórico de 09/11/2026) |
| [docs/research/01-pesquisa-stack-backend.md](docs/research/01-pesquisa-stack-backend.md) | Pesquisa da stack: FastAPI, auth, RBAC, LDAP, OIDC, S3, ferramentas |
| [docs/architecture/arquitetura-conceitual.md](docs/architecture/arquitetura-conceitual.md) | Papéis, recursos, matriz de permissões, componentes, fluxos, rotas |
| [docs/architecture/modelo-dados.md](docs/architecture/modelo-dados.md) | Tabelas e relacionamentos |
| [docs/adr/](docs/adr/) | Decisões arquiteturais (ADR-0001 a 0011) |
| [specs/](specs/) | Specs SDD 001 a 012 (requisitos EARS, design, tarefas), rastreabilidade e calendário |
| [AGENTS.md](AGENTS.md), [CLAUDE.md](CLAUDE.md), [steering/](steering/) | Contexto e regras para agentes de código |
| [.claude/commands/](.claude/commands/) | Comandos do fluxo SDD no Claude Code |
| [.github/](.github/) | CI e template de PR |

## Registros históricos
Preservados como foram escritos; cada um traz a própria data e o commit que descreve. **Não refletem** a interface da Etapa 06 (spec 012, emenda funcional 2: qualidade, histórico, referências, ficha, serviços, desativação, cadastro e edição) nem a **aprovação formal do cenário D** das 30 tuplas, que está registrada em [docs/banco/06-trinta-tuplas.md](docs/banco/06-trinta-tuplas.md). Para o estado atual, use a documentação oficial do topo deste README.

| Documento | Data e estado descrito |
|---|---|
| Relatório geral de andamento: [Markdown](docs/RELATORIO_GERAL_ANDAMENTO_SGS_RECIFE.md) · [PDF](docs/RELATORIO_GERAL_ANDAMENTO_SGS_RECIFE.pdf) | 10/11/2026, `main` em `4a07f71` |
| Relatório de implementação: [Markdown](docs/RELATORIO_IMPLEMENTACAO_SGS_RECIFE.md) · [PDF](docs/RELATORIO_IMPLEMENTACAO_SGS_RECIFE.pdf) | 10/11/2026, `main` em `4a07f71` |
| Guia de execução, uso e testes: [Markdown](docs/GUIA_EXECUCAO_LOCAL_SGS_RECIFE.md) · [PDF](docs/GUIA_EXECUCAO_LOCAL_SGS_RECIFE.pdf) | 10/11/2026, `main` em `4a07f71`. Os comandos de execução seguem úteis; para a demonstração, use o roteiro `08` |
| [docs/RESUMO_STATUS_PROJETO.md](docs/RESUMO_STATUS_PROJETO.md) | 09/11/2026, depois da consolidação |
| [docs/RELATORIO_VALIDACAO_FINAL.md](docs/RELATORIO_VALIDACAO_FINAL.md) | 09/11/2026 |
| [docs/REQUISITOS_EVIDENCIAS.md](docs/REQUISITOS_EVIDENCIAS.md) | 09/11/2026 (substituída pela matriz `07`) |
| [docs/RELATORIO_PR_PUBLICACAO.md](docs/RELATORIO_PR_PUBLICACAO.md), [docs/CHECKPOINT_CONSOLIDACAO.md](docs/CHECKPOINT_CONSOLIDACAO.md) | 09/11/2026 |
| [docs/PLANO_INTEGRACAO_FRONTEND.md](docs/PLANO_INTEGRACAO_FRONTEND.md) | 09/11/2026 (planejamento; a implementação está na spec 012) |
| [docs/integration-audit/](docs/integration-audit/) | 09/11/2026 (auditoria das branches e plano de consolidação) |

## Ordem de implementação sugerida
Ver o calendário em [specs/README.md](specs/README.md#ordem-e-calendário-sugeridos): fundação e login primeiro, depois RBAC e cadastro, validação e dados de demonstração, histórico e dashboard, e por fim LDAP/OIDC e exportação S3.

## Pendências para o grupo
Situação em 10/11/2026, conferida nos `tasks.md` de cada spec. O resumo de 09/11 ([docs/RESUMO_STATUS_PROJETO.md](docs/RESUMO_STATUS_PROJETO.md)) é registro histórico (§ Registros históricos).

**Entrega final de Banco de Dados (13/11/2026):** implementada e validada (ver § Demonstração da interface e [docs/banco/07-matriz-conformidade.md](docs/banco/07-matriz-conformidade.md)). Falta consolidar os commits e publicar.

**Planejadas para 21/11/2026** (escopo mínimo da spec 012; não fazem parte da entrega de 13/11):
- T8 parte B e T11 parte B: as 8 verificações de qualidade, na ficha e no painel;
- T12 (funcionalidades sem backend visíveis e desabilitadas), T13 (XSS de ponta a ponta e responsividade) e T14 (E2E no CI e documentação).

**Pendentes de implementação nas specs aprovadas** (tarefas `[ ]` no `tasks.md`, sem bloqueio pendente registrado e sem prazo definido; nenhuma foi iniciada):
- **003/T8** (não implementada): mapeamento grupo → papel e recálculo das atribuições derivadas (R3.1 a R3.3). Só o pré-requisito registrado, 003/T7, está concluído. Observação, fora do `tasks.md`: os grupos vêm do diretório (LDAP e OIDC), objeto da spec 004, que segue em Rascunho;
- **006/T10** (não implementada): teste de desempenho da busca (R2.7: menos de 3 s em 95% das requisições, com 1.000 unidades). O pré-requisito registrado, 006/T4, está concluído;
- **009/T3** (não implementada): teste de desempenho do dashboard (R1.7: menos de 1 s com 1.000 unidades). Sem pré-requisito registrado na tarefa; o cabeçalho do `tasks.md` da 009 lista "Depende de: 006, 007, 008";
- **009/T2b** (não implementada, condicional): cache com invalidação por versão (R1.7), só se a 009/T3 mostrar p95 acima de 1 s. Substitui a T2 original, adiada na revisão de 09/11/2026;
- **010/T3** (não implementada): conversor da planilha de rede com relatório de rejeitos (R2.1 e R2.2). O `tasks.md` não registra bloqueio; o requisito R2.1 condiciona o conversor a o grupo ter a planilha `REDE_SAUDE_RECIFE_GEO`.

Ver também [docs/relatorios/REGULARIZACAO_GOVERNANCA_SPECS.md](docs/relatorios/REGULARIZACAO_GOVERNANCA_SPECS.md).

**Bloqueadas por dependências externas** (decisões do cliente ou specs de outros donos, registradas em "Bloqueada por"): spec 012, T15 a T23 (aparelhos, solicitações, notificações, campos da unidade, revisão, histórico no escopo do distrito, exportação e importação, usuários, leitura por escopo; ver o `tasks.md` da 012).

**Specs ainda em Rascunho:** 004 (LDAP e OIDC), 005 (exportação para S3) e 007 (validação de dados).

**Outros:** confirmar FastAPI e atualizar o Documento de Arquitetura da Atividade 5 (ADR-0001).
