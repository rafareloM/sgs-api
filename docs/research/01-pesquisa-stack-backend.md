# Pesquisa da stack de backend

> Plataforma de Governança de Dados de Saúde · SESAU Recife · Grupo 01
> Pesquisa feita em 03/10/2026. Versões conferidas no PyPI nessa data.

## 1. Resumo da decisão

| Camada | Escolha | Versão de referência | Por quê |
|---|---|---|---|
| Linguagem | Python | 3.13 | Versão estável com suporte amplo de todas as libs abaixo |
| Framework HTTP | FastAPI | 0.142.x | OpenAPI automático, validação com Pydantic, injeção de dependências usada para auth/RBAC |
| Servidor ASGI | Uvicorn | 0.54.x | Padrão do FastAPI; `--proxy-headers` atrás do proxy TLS |
| Validação / schemas | Pydantic v2 + pydantic-settings | 2.13 / 2.15 | Valida entrada (RF-03, RS-08) e configuração por variáveis de ambiente |
| ORM | SQLAlchemy 2.x (async) | 2.1.x | Tipagem moderna (`Mapped[]`), maduro, suporta PostgreSQL a fundo |
| Driver PostgreSQL | asyncpg | 0.31.x | Driver assíncrono mais rápido; TLS configurável |
| Migrações | Alembic | 1.20.x | Padrão para SQLAlchemy; migrações versionadas no Git |
| Banco | PostgreSQL | 17 | Já definido pelo grupo; JSONB, RLS opcional, `pgcrypto` |
| Hash de senha | pwdlib[argon2] | 0.3.x | Recomendado pela documentação atual do FastAPI (substitui passlib) |
| JWT | PyJWT[crypto] | 2.15.x | Recomendado pela documentação atual do FastAPI (substitui python-jose); suporta ES256/EdDSA |
| 2FA (TOTP) | pyotp | 2.10.x | TOTP RFC 6238, compatível com Google Authenticator/FreeOTP |
| OIDC | Authlib | 1.8.x | Cliente OIDC com descoberta, PKCE, validação de `id_token` e JWKS |
| LDAP | ldap3 | 2.9.1 | Puro Python, sem libldap no container, tem servidor *mock* para testes |
| S3 | boto3 (+ types-boto3) | 1.43.x | SDK oficial da AWS: SigV4, STS, URLs pré-assinadas, checksums |
| Criptografia de campo | cryptography | 50.x | AES-256-GCM (RS-04) e chaves assimétricas |
| Logs | structlog | 26.x | Logs JSON com `request_id` e usuário |
| Rate limit | slowapi | 0.1.x | Limita tentativas de login (RS-09) |
| Testes | pytest, pytest-asyncio, httpx, testcontainers, moto, schemathesis, hypothesis | — | Unidade, integração com Postgres real, S3 simulado, contrato OpenAPI |
| Qualidade | uv, ruff, mypy, import-linter, bandit, pip-audit, pre-commit | — | Gerência de dependências, lint, tipos, arquitetura, segurança |

## 2. FastAPI e o núcleo da API

**Pontos que usamos de propósito**

- **Dependências (`Depends`) como mecanismo de segurança.** Autenticação e autorização viram dependências reutilizáveis: `CurrentUser`, `require("unidade:update")`. Cada rota declara explicitamente a permissão que exige, e um teste varre o app para garantir que nenhuma rota de `/api/v1` fica sem permissão declarada (deny by default).
- **OpenAPI como contrato.** O FastAPI gera `/openapi.json` a partir dos schemas Pydantic. Na esteira SDD, o contrato é congelado em `contracts/openapi.yaml` e o CI falha se o código divergir sem atualizar a spec (ver `steering/sdd-workflow.md`).
- **`lifespan`** para abrir e fechar pool do banco, clientes LDAP/S3 e carregar chaves JWT.
- **`BackgroundTasks`** para gerar relatórios sem travar a requisição no MVP. Se o volume crescer, troca-se por um worker (arq ou Celery) sem mudar a interface do módulo de relatórios.
- **Erros no formato RFC 9457 (`application/problem+json`)**, com um handler único. Erros de validação (422) viram mensagens legíveis para o front, cumprindo o critério "dado inválido gera mensagem clara e não é gravado".

**Atenção**

- FastAPI ainda está em versão 0.x: fixar a versão no `uv.lock` e atualizar de forma controlada.
- Rotas `async def` não podem chamar bibliotecas bloqueantes (ldap3, boto3) diretamente. Essas chamadas vão para `anyio.to_thread.run_sync` / `run_in_threadpool` dentro dos adaptadores.

## 3. Persistência

- **SQLAlchemy 2.x async + asyncpg.** Sessão por requisição via dependência; transação aberta no início do caso de uso e confirmada no fim, junto com o registro de auditoria (mesma transação: se a auditoria falhar, a alteração também falha).
- **Alembic** com `autogenerate` só como rascunho; toda migração é revisada. Triggers de auditoria e restrições ficam em migrações explícitas.
- **TLS até o banco (RS-03).** `sslmode=verify-full` no asyncpg via `ssl` context; em desenvolvimento, certificado autoassinado gerado no compose.
- **Criptografia em repouso (RS-04).** Duas camadas: volume/disco criptografado (responsabilidade da infraestrutura) e criptografia de campo AES-256-GCM para segredos (segredo TOTP, tokens de terceiros). Cada valor cifrado leva nonce aleatório de 96 bits e versão da chave (`v1:nonce:ciphertext`), o que atende a orientação da Prof.ª Renatta sobre gestão de IV/nonce e rotação de chaves. A chave mestra vem de variável de ambiente no desenvolvimento e de um KMS em produção (criptografia envelope).
- **SQLModel foi descartado**: mistura schema de API e modelo de banco, o que atrapalha separar camadas e esconder campos sensíveis.

## 4. Autenticação

### 4.1 Login local (usuário e senha + 2FA)

- Senhas com **Argon2id** (`pwdlib`). Para usuário inexistente, o login ainda verifica contra um hash fictício, como recomenda a documentação do FastAPI, para não permitir descobrir usuários pelo tempo de resposta.
- **2FA por TOTP** (`pyotp`): decisão já registrada na Atividade 5 (seção 3.1). Fluxo em duas etapas: senha correta devolve um `mfa_token` de 5 minutos com finalidade única; o código TOTP troca esse token pelos tokens de acesso. SMS foi descartado (custo e SIM swap).
- **Tokens.**
  - *Access token* JWT de 15 min, assinado com **ES256** (chave assimétrica, com `kid`), publicado em `/.well-known/jwks.json`. Assinatura assimétrica permite que outros serviços validem o token sem conhecer o segredo, e segue a orientação da disciplina de criptografia.
  - *Refresh token* opaco, guardado no banco apenas como hash, com rotação a cada uso e detecção de reuso (se um refresh antigo reaparecer, toda a família é revogada). Vai em cookie `HttpOnly; Secure; SameSite=Strict; Path=/api/v1/auth`.
  - Claims mínimas no JWT: `sub`, `sid`, `iat`, `exp`, `iss`, `aud`, `amr`. **Permissões não vão no token**: são resolvidas no servidor a cada requisição (com cache curto), para que revogar um papel tenha efeito imediato.
- **CSRF (RS-08).** Como só o refresh usa cookie, o endpoint de refresh exige um cabeçalho customizado (`X-Requested-With`) e checa `Origin`. As demais rotas usam `Authorization: Bearer`, imunes a CSRF.
- **Rate limiting** no login e na verificação de 2FA (ex.: 5 tentativas/min por IP e por usuário) e bloqueio temporário após falhas (RS-09).

### 4.2 OIDC (OpenID Connect)

- **Fluxo Authorization Code + PKCE** com o backend como cliente confidencial (padrão BFF). O navegador nunca vê o `client_secret`.
- Authlib faz a descoberta (`/.well-known/openid-configuration`), troca o código e valida o `id_token` (assinatura via JWKS, `iss`, `aud`, `exp`, `nonce`).
- **Provisionamento just-in-time:** no callback, o usuário é criado ou atualizado na tabela local (`source = oidc`, `external_id = sub`), e a claim `groups` é sincronizada para a tabela local de grupos. Depois disso a API emite os **próprios** tokens; a sessão interna é a mesma do login local.
- 2FA no login OIDC fica a cargo do provedor; a API pode exigir `acr`/`amr` adequados por configuração.
- **IdP de desenvolvimento: Keycloak 26.x** (container oficial `quay.io/keycloak/keycloak`). Ele também federa o LDAP (*User Federation* + *group-ldap-mapper*), o que permite demonstrar o mesmo usuário entrando por LDAP direto e por OIDC.

### 4.3 LDAP

Dois usos distintos, ambos dentro do módulo `identity`:

1. **Autenticação por bind.** A API conecta com uma conta de serviço, busca o DN do usuário pelo `uid`/`mail`, e faz *bind* com o DN e a senha informados. Sempre sobre **LDAPS (636) ou StartTLS**; nunca bind simples em texto claro.
2. **Sincronização de diretório.** Um job (disparado por endpoint administrativo e opcionalmente agendado) faz busca paginada (*Simple Paged Results*, RFC 2696) de usuários (`inetOrgPerson`) e grupos (`groupOfNames`), e faz *upsert* nas tabelas locais `users`, `groups` e `user_groups`. Quem sumiu do diretório é desativado, nunca apagado (preserva a auditoria). Cada execução gera um registro em `directory_sync_runs` com contagens e erros.

**Biblioteca: ldap3.** É puro Python, então o container não precisa de `libldap`, e tem a estratégia `MOCK_SYNC` que simula um servidor em memória para testes unitários. **Risco:** o projeto tem pouca manutenção ativa. Mitigação: o acesso fica atrás de uma porta (`DirectoryPort`) e pode ser trocado por `python-ldap` 3.4.x (mantido, mas depende de bibliotecas C) sem tocar no resto do código.

**Segurança:** todo valor que entra em filtro LDAP passa por `ldap3.utils.conv.escape_filter_chars` (prevenção de LDAP injection, RS-08). Atributos lidos são limitados a uma lista explícita.

**Servidor de desenvolvimento:** as imagens gratuitas da Bitnami (incluindo `bitnami/openldap`) foram retiradas do Docker Hub e a `osixia/openldap` está sem manutenção. Recomendação: OpenLDAP a partir de um Dockerfile próprio baseado em Debian (`slapd` + LDIF de seed com `ou=distritos`, `ou=grupos`), ou `lldap` se o grupo preferir algo mais leve (perde a árvore de OUs customizada, que é útil para a disciplina).

## 5. Autorização (RBAC)

- **Modelo próprio em tabelas** (`roles`, `permissions`, `role_permissions`, `role_assignments`) em vez de Casbin. O requisito da disciplina é *implementar* RBAC; tabelas próprias deixam o modelo visível no banco, auditável e fácil de explicar na apresentação. Casbin (pycasbin 2.8) fica registrado como alternativa.
- **RBAC com escopo.** A atribuição de papel tem um escopo: `global`, `distrito`, `unidade` ou `area_tecnica`. Isso resolve o critério "um gestor de unidade não deve conseguir editar dados de outra unidade" sem cair em ABAC completo.
- Papéis podem ser atribuídos a **usuários** ou a **grupos** (vindos do LDAP/OIDC), via tabela de mapeamento `group_role_mappings`. É aqui que o requisito de LDAP/OIDC se conecta ao RBAC.
- Permissões no formato `recurso:ação` (ex.: `unidade:update`, `auditoria:read`, `relatorio:export`).
- Listagens aplicam o escopo como filtro SQL (o usuário só vê o que pode ver); operações em um recurso específico checam o escopo antes de executar.
- **Privilégio mínimo e segregação de funções**, como pediu o Prof. Caio: quem administra usuários (TI) não edita cadastro; quem audita não altera dados.

## 6. Exportação de relatórios para S3

- **SDK:** boto3 (síncrono, executado em thread). aioboto3 foi avaliado, mas acrescenta uma camada que segue o boto3 com atraso.
- **Autenticação avançada com a AWS:**
  - Toda chamada é assinada com **SigV4** (feito pelo SDK).
  - **Sem chaves fixas em produção.** A API usa a cadeia padrão de credenciais e faz **STS `AssumeRole`** para um papel IAM restrito ao prefixo `reports/` do bucket, com `ExternalId`, `RoleSessionName` contendo o id do usuário e duração de 15 min. O CloudTrail passa a mostrar quem exportou o quê.
  - **Evolução opcional:** `AssumeRoleWithWebIdentity` usando o token do Keycloak, ligando a identidade OIDC diretamente à permissão no S3.
  - Download por **URL pré-assinada** de curta duração (5 min), emitida só para quem tem `relatorio:download`.
- **Integridade e confidencialidade:** upload com `ChecksumAlgorithm=SHA256`, criptografia do lado do servidor (`SSE-KMS` em produção, `SSE-S3` como mínimo), bucket com *Block Public Access* e política que nega requisições sem TLS (`aws:SecureTransport = false`). O hash do arquivo também é gravado na auditoria.
- **Formatos do MVP:** CSV (UTF-8 com BOM, para abrir certo no Excel) e XLSX via openpyxl, atendendo RNF-05. PDF fica fora.
- **S3 local:** a MinIO deixou de publicar imagens em outubro de 2025 e arquivou o repositório em abril de 2026; o LocalStack passou a exigir conta desde março de 2026. Recomendação: **SeaweedFS** (Apache 2.0) no docker-compose de desenvolvimento e **moto** nos testes automatizados. O código é o mesmo; só muda `S3_ENDPOINT_URL`.

## 7. Observabilidade e operação

- `structlog` com JSON, `request_id` por requisição (cabeçalho `X-Request-ID`), usuário e rota. Nunca logar senha, token ou segredo TOTP (filtro de chaves sensíveis).
- `/health/live` e `/health/ready` (ready checa banco).
- Auditoria de **acessos** (login, falha de login, troca de senha, exportação) além de alterações, com retenção de 2 anos (RS-05).
- Docker Compose com `api`, `db`, `ldap`, `keycloak`, `s3` e um proxy TLS (Caddy) na frente da API para HTTPS local (RS-03).

## 8. Ferramentas da esteira

| Ferramenta | Papel na esteira |
|---|---|
| uv | Ambiente e lockfile reprodutível (`uv sync --frozen` no CI) |
| ruff | Lint + formatação |
| mypy (strict nos módulos de domínio) | Tipos |
| import-linter | Garante as camadas (domínio não importa FastAPI nem SQLAlchemy) |
| pytest + testcontainers | Testes de integração contra PostgreSQL real |
| moto | S3 e STS simulados |
| ldap3 MOCK_SYNC | Diretório simulado |
| schemathesis | Testes gerados a partir do OpenAPI |
| bandit + pip-audit | SAST e dependências vulneráveis |
| pre-commit | Roda o básico antes de cada commit |
| GitHub Actions | CI com os mesmos comandos |

## 9. Alternativas descartadas

| Alternativa | Motivo |
|---|---|
| Node.js/TypeScript | Era a escolha registrada na Atividade 5; este pedido fixa FastAPI. Ver ADR-0001 |
| Django + DRF | Mais pesado para uma API pura; admin e ORM próprios não são necessários |
| fastapi-users | Acelera login, mas esconde o modelo de usuário e RBAC que a disciplina quer ver implementado |
| python-jose / passlib | Pouca manutenção; a documentação do FastAPI migrou para PyJWT / pwdlib |
| Casbin | Bom motor, mas o requisito é implementar o RBAC e explicar o modelo |
| MinIO / LocalStack | Fim das imagens gratuitas (ver seção 6) |
| Microsserviços / filas | Complexidade sem benefício para ~250 unidades; decisão já registrada na Atividade 3 |

## Fontes

- FastAPI, OAuth2 com senha e JWT (PyJWT, pwdlib, mitigação de timing attack): https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/
- FastAPI, OAuth2 scopes: https://fastapi.tiangolo.com/advanced/security/oauth2-scopes/
- Keycloak 26.6.0: https://www.keycloak.org/2026/04/keycloak-2660-released
- Keycloak, federação LDAP: https://www.keycloak.org/docs/latest/server_admin/index.html
- MinIO arquivado e alternativas: https://pinggy.io/blog/minio_archived_self_hosted_s3_alternatives/
- LocalStack exige conta desde 23/03/2026: https://github.com/testcontainers/testcontainers-java/issues/11568
- Bitnami retirou imagens gratuitas: https://northflank.com/blog/bitnami-deprecates-free-images-migration-steps-and-alternatives
- Versões: consultadas via `pip index versions` no PyPI em 03/10/2026
