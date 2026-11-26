# 004 · Diretório LDAP e OIDC · Design

- Status: **Aprovado (G2: Rafael (rafareloM), dono, em 24/11/2026)**. Registro do agente por autorização expressa dada na sessão de trabalho, com as recomendações de § Pontos para o G2 aceitas (§ Decisões do G2). Aprovação só do dono, pela exceção de `steering/sdd-workflow.md` § Exceção pontual: specs 004 e 005. **Limitação: o design não teve revisão de um segundo integrante.**
- Requisitos: requirements.md (Aprovado, G1 do Rafael em 24/11/2026)
- Decisões: ADR-0003 (identidade federada com tokens próprios, Aceito). Emenda 2 do ADR-0007 (httpx como dependência de execução, D004-4), aceita no G2.
- Histórico: rascunho de 03/10/2026 (portas, configuração, algoritmo da sincronização); notas de 09/11/2026 e 24/11/2026 ("Ajustes pendentes do G1"); reescrito por agente em 24/11/2026 com `/spec-design`, depois do G1, aplicando aquelas notas e cobrindo os critérios novos (R1.13, R1.14, R3.7–R3.9, R4.3, R4.4, R5). Emendado em 25/11/2026 com as decisões de execução do Rafael (§ Decisões de execução).

## Visão geral
A API passa a aceitar três origens de identidade. Todas terminam no mesmo lugar: uma linha em `users`, grupos espelhados em `groups` e `user_groups`, atribuições derivadas pelo mapeamento da spec 003 e os tokens próprios da spec 002 (ADR-0003).

1. **Sincronização LDAP.** Disparada pelo Admin TI ou pelo agendador. Lê o diretório inteiro por LDAPS com a conta de serviço, fora de qualquer transação, e aplica tudo numa transação só: cria, atualiza e desativa usuários e grupos, troca as associações e recalcula as atribuições derivadas.
2. **Login LDAP.** É o login da 002 com `provider = "ldap"`. A senha é conferida por *bind* no diretório; o resto (bloqueio, 2FA, sessão, auditoria) é o fluxo da 002, com `amr = "ldap+otp"`.
3. **Login OIDC.** Authorization Code com PKCE S256. O `state` fica no banco, com uso único, e é preso ao navegador por um cookie. No callback, a API confere o `id_token`, provisiona o usuário, abre a sessão da 002 (cookie de refresh) e redireciona ao front-end. O front obtém o access token pela renovação que já faz na abertura.
4. **Ambiente de laboratório.** `slapd` só com LDAPS e Keycloak com realm próprio no compose. Os certificados vêm de uma CA de desenvolvimento gerada na subida, compartilhada com a spec 005.

## Diagnóstico de partida (24/11/2026, `main` @ `62b373c`)
| Item | Situação |
|---|---|
| `users` | Já tem `source` (`local`/`ldap`/`oidc`), `external_id`, `synced_at`, único em (`source`, `external_id`); `username` e `email` únicos em todas as origens |
| `groups`, `user_groups`, `directory_sync_runs` | Não existem (`docs/architecture/modelo-dados.md` § 1) |
| `group_role_mappings.group_id` | Sem FK, esperando `groups` (comentário em `access/infrastructure/tables.py`) |
| Permissões `diretorio:sync` e `papel:assign` | Semeadas na `0003_access`, só para `ADMIN_TI` |
| 003/T8 (mapeamento e recálculo) | Só na `origin/feat/011-integracao` (`access/application/mapeamentos.py`: `recalcular_derivadas_do_usuario`, porta `MembrosDeGrupo`); fora da `main` |
| Login (002) | `POST /auth/login` só local (`LoginIn` com `extra="forbid"`, sem `provider`); `_concluir_mfa` sempre abre a sessão com `amr = "pwd+otp"` |
| Cookie de refresh | `sgs_refresh`, `HttpOnly; Secure; SameSite=Strict; Path=/api/v1/auth`; `/auth/refresh` exige `X-Requested-With: sgs` e `Origin` em `CORS_ORIGINS` |
| Dependências | `ldap3` e `Authlib` estão na `steering/tech.md`, mas não no `pyproject.toml`; `httpx` só no grupo `dev` |
| Compose | Sem LDAP nem Keycloak; `.env.example` reserva `LDAP_*` e `OIDC_*` |
| Front (012) | A abertura faz refresh silencioso → `/me` → menu; a tela de login não tem entrada OIDC |

## Rotas (contrato)
| Método e rota | Permissão | Entrada | Saída | Erros | Requisitos |
|---|---|---|---|---|---|
| `POST /api/v1/admin/diretorio/sincronizar` | `diretorio:sync` | sem corpo | 202 `{execucao_id, status: "em_andamento"}` | 401, 403, 409 (já há execução em andamento), 503 (LDAP não configurado) | R1.1, R1.11 |
| `GET /api/v1/admin/diretorio/execucoes` | `diretorio:sync` | `pagina`, `tamanho` | 200 `{itens: [Execucao], total}`, da mais recente para a mais antiga | 401, 403, 422 | R1.9 |
| `GET /api/v1/admin/diretorio/execucoes/{id}` | `diretorio:sync` | — | 200 `Execucao` | 401, 403, 404 | R1.9, R1.10, R4.2 |
| `GET /api/v1/admin/diretorio/grupos` | `papel:assign` | `origem` (`ldap`/`oidc`), `ativo` (padrão `true`), `busca` (até 100 caracteres, no nome), `pagina`, `tamanho` | 200 `{itens: [{id, origem, nome, membros_ativos, ativo}], total}` | 401, 403, 422 | R1.14 |
| `POST /api/v1/auth/login` | pública | `{username, password, provider: "local" \| "ldap"}`; `provider` opcional, padrão `"local"` | 200 `LoginOut` (o mesmo da 002) | 401 genérico, 422, 429, 503 (diretório indisponível) | R2.1–R2.4, R4.1, R4.3, R4.4 |
| `GET /api/v1/auth/provedores` | pública | — | 200 `{ldap: bool, oidc: bool}` | — | R3.9 |
| `GET /api/v1/auth/oidc/login` | pública | — | 302 para o provedor, com o cookie de vínculo `sgs_oidc` | 404 (OIDC não configurado), 429 | R3.1, R3.8 |
| `GET /api/v1/auth/oidc/callback` | pública | `code` e `state`, ou `error` e `state`; cookie `sgs_oidc` | 302 para `FRONTEND_URL`, com o cookie de refresh; ou 302 para `FRONTEND_URL?login_erro=oidc` | sempre 302, nunca JSON | R3.2–R3.8, R4.3, R4.4 |

`Execucao` = `{id, tipo: "ldap", status: "em_andamento" | "concluida" | "falhou", iniciada_em, concluida_em, disparada_por (id ou null, se agendada), usuarios: {criados, atualizados, desativados}, grupos: {criados, atualizados, desativados}, conflitos: [{tipo: "email" | "username", external_id, usuario_existente_id}], erro (texto genérico ou null)}`. Os conflitos não trazem o e-mail nem o nome: o Admin TI chega à conta pelo id (LGPD, `steering/security.md`).

As três rotas públicas novas entram na lista de `tests/architecture/test_rotas_protegidas.py` (`PUBLICAS`), com a justificativa ao lado: `provedores` só diz se cada origem está ligada; `oidc/login` e `oidc/callback` acontecem antes de existir usuário. `GET /auth/oidc/login` tem limite por IP (20 por minuto, instância própria do `LimiteDeRequisicoes`), porque cada chamada grava uma linha.

## Modelo de dados / migrações
Migração `0004_diretorio` (Alembic, SQLAlchemy Core: o módulo `identity` fica fora do ADR-0009). Tabelas declaradas em `identity/infrastructure/tables.py`, iguais à migração (`test_migracoes_sincronizadas`).

| Tabela | Colunas | Restrições e índices | Requisitos |
|---|---|---|---|
| `groups` | `id` (uuid v7), `source` (`ldap`/`oidc`), `external_id` (até `EXTERNAL_ID_MAX`), `name` (até 255), `description` (nulo), `is_active`, `synced_at`, timestamps | único (`source`, `external_id`); `CHECK source IN ('ldap','oidc')`; nunca apagado, só desativado (mantém as FKs dos mapeamentos) | R1.8, R1.14, R3.3 |
| `user_groups` | `user_id` → `users`, `group_id` → `groups`, `source` (`ldap`/`oidc`), `created_at` | PK (`user_id`, `group_id`); `ix_user_groups_group_id` (contagem de membros e `MembrosDeGrupo`) | R1.8, R1.14, R3.3 |
| `directory_sync_runs` | `id`, `kind` (`ldap`), `status` (`em_andamento`/`concluida`/`falhou`), `started_at`, `finished_at`, `triggered_by` → `users` (nulo se agendada), `users_created`, `users_updated`, `users_deactivated`, `groups_created`, `groups_updated`, `groups_deactivated` (inteiros ≥ 0), `conflicts` (JSONB, lista), `error` (até 200, genérico) | `ux_directory_sync_runs_em_andamento` único em (`kind`) `WHERE status = 'em_andamento'` (R1.11, D004-1); `ix_directory_sync_runs_started_at` | R1.9–R1.11, R4.2 |
| `oidc_login_requests` | `id`, `state_hash` (SHA-256 em hex), `binding_hash` (SHA-256 em hex), `nonce` (até 64), `code_verifier_enc` (`FieldCipher`, AAD = `id`), `created_at`, `expires_at`, `used_at` | único em `state_hash`; `CHECK expires_at > created_at` | R3.1, R3.2, R3.7 |
| `group_role_mappings` | — | FK nova `group_id` → `groups.id` (`ON DELETE RESTRICT`) | R1.14; 003/R3.1 |

- Os privilégios do `sgs_app` vêm do *default privilege* da `0001` (SELECT, INSERT, UPDATE, DELETE). `oidc_login_requests` precisa de DELETE para a limpeza; as outras três não são apagadas pela aplicação.
- A FK de `group_role_mappings` só entra se nenhuma linha tiver `group_id` órfão. A migração confere antes e para com mensagem clara. Hoje a tabela está vazia, porque a 003/T8 não está na `main`.
- `docs/architecture/modelo-dados.md` § 1: tira a nota "Ainda não implementadas" e acrescenta `oidc_login_requests`.

## Portas e adaptadores
No domínio (`identity/domain/diretorio.py`, `identity/domain/oidc.py`), só stdlib:

```python
@dataclass(frozen=True)
class DirectoryUser:
    external_id: str          # entryUUID/objectGUID; o DN se LDAP_ATTR_ID estiver vazio (R1.5)
    dn: str
    login: str                # minúsculo
    email: str | None         # minúsculo
    display_name: str

@dataclass(frozen=True)
class DirectoryGroup:
    external_id: str
    dn: str
    name: str
    member_dns: frozenset[str]

@dataclass(frozen=True)
class DirectorySnapshot:
    users: tuple[DirectoryUser, ...]
    groups: tuple[DirectoryGroup, ...]

class DirectoryUnavailable(Exception):
    """Conexão, TLS recusado (R1.13), timeout ou erro do servidor. Nunca leva a senha."""

class DirectoryPort(Protocol):
    async def snapshot(self) -> DirectorySnapshot: ...                     # R1.2–R1.4
    async def find_user(self, login: str) -> DirectoryUser | None: ...     # R2.1, R2.2
    async def verify_password(self, dn: str, password: str) -> bool: ...   # R2.1, R2.4
    async def groups_of(self, user: DirectoryUser) -> tuple[DirectoryGroup, ...]: ...  # R2.3

@dataclass(frozen=True)
class OidcIdentity:
    sub: str
    username: str             # preferred_username, minúsculo
    email: str | None         # só com email_verified = true (D004-12)
    display_name: str
    groups: tuple[str, ...]   # claim OIDC_GROUPS_CLAIM
    acr: str | None

class OidcRejected(Exception):
    def __init__(self, motivo: str) -> None: ...   # lista fechada, ver § Fluxo OIDC

class OidcPort(Protocol):
    async def authorization_url(self, *, state: str, nonce: str, code_challenge: str) -> str: ...  # R3.1, R3.8
    async def exchange(self, code: str, *, code_verifier: str, nonce: str) -> OidcIdentity: ...  # R3.2, R3.6
```

O plano da sincronização é uma função pura do domínio, testada sem banco: `planejar(retrato, locais) -> PlanoDeSincronizacao` (criações, atualizações, desativações, conflitos, grupos e associações).

Adaptadores (`identity/infrastructure/`):
- **`ldap3_directory.py`.** `ldap3.Server(host, port, use_ssl=True, tls=Tls(validate=CERT_REQUIRED, ca_certs_file=LDAP_CA_FILE, version=TLSv1_2 ou maior, valid_names=[host]), connect_timeout=5)`. Para `ldap://` com StartTLS: `auto_bind=AUTO_BIND_TLS_BEFORE_BIND`. Assim o TLS é negociado e o certificado conferido antes de qualquer bind (R1.13).
  - `Connection(read_only=True, receive_timeout=10)`; busca com `extend.standard.paged_search(paged_size=LDAP_PAGE_SIZE)` e só os atributos configurados (R1.4).
  - Todo valor que entra em filtro passa por `ldap3.utils.conv.escape_filter_chars` (R2.2).
  - `verify_password` abre uma conexão nova com o DN do usuário e recusa senha vazia antes do bind (R2.4).
  - Cada chamada roda em `anyio.to_thread.run_sync` (`steering/tech.md`).
  - Erros do `ldap3` (`LDAPSocketOpenError`, `LDAPSSLConfigurationError`, `LDAPStartTLSError`, timeouts) viram `DirectoryUnavailable`. A senha nunca entra em log nem em exceção.
- **`authlib_oidc.py`.**
  - `authlib.integrations.httpx_client.AsyncOAuth2Client` faz a URL de autorização (`code_challenge_method="S256"`) e a troca do código (`client_secret_basic`).
  - O transporte é `httpx` com `verify` = contexto TLS do `OIDC_CA_FILE` (ou do sistema) e timeout de 10 s.
  - A descoberta vem de `OIDC_DISCOVERY_URL`. O `issuer` do documento tem de ser igual a `OIDC_ISSUER`; se não for, a API não usa o provedor.
  - O `id_token` é conferido com o PyJWT (D004-3):
    - `algorithms` fixos em `["RS256", "ES256"]`;
    - chave pelo `kid` no JWKS em cache; um `kid` desconhecido recarrega o JWKS uma vez, no máximo uma vez por minuto;
    - `iss = OIDC_ISSUER`, `aud` contém `OIDC_CLIENT_ID` (com mais de uma audiência, `azp = OIDC_CLIENT_ID`);
    - `exp` e `iat` com tolerância de 60 s;
    - `require = ["exp", "iat", "iss", "aud", "sub", "nonce"]`;
    - `nonce` igual ao guardado.
- **Repositórios** (SQLAlchemy Core): `SqlDirectoryRepository` (`groups`, `user_groups`, `directory_sync_runs`, upserts por `ON CONFLICT (source, external_id)`), `SqlOidcLoginRequests` e o adaptador de `MembrosDeGrupo` da 003 (leitura de `user_groups` com `users.is_active`).
- **Recálculo.** `identity.application` chama `access.application.mapeamentos.recalcular_derivadas_do_usuario(usuario_id, grupos)` na mesma transação, como a 003/T8 fixou; o import-linter permite `application` de outro módulo. As fábricas dos repositórios de acesso vêm de `app.state`, como no login.

## Configuração
Lida só por `Settings` (`src/core/config.py`). Sem `LDAP_URL`, o LDAP fica desligado; sem `OIDC_ISSUER`, o OIDC fica desligado (`/auth/provedores` diz qual está ligado).

| Variável | Exemplo (laboratório) | Regra na subida | Requisitos |
|---|---|---|---|
| `LDAP_URL` | `ldaps://ldap:636` | `ldaps://`, ou `ldap://` só com `LDAP_START_TLS=true`; qualquer outro esquema é recusado | R1.2 |
| `LDAP_START_TLS` | `false` | — | R1.2 |
| `LDAP_CA_FILE` | `/certs-servicos/ca.crt` | obrigatória com `LDAP_URL`; arquivo existente | R1.2, R1.13 |
| `LDAP_BIND_DN` / `LDAP_BIND_PASSWORD` | `cn=sgs-sync,ou=servicos,dc=recife,dc=pe,dc=gov,dc=br` / `sgs-lab-exemplo-bind` | obrigatórias com `LDAP_URL`; em `prod`, senha de exemplo recusada | R1.3, R5.4 |
| `LDAP_USER_BASE` / `LDAP_USER_FILTER` | `ou=pessoas,...` / `(objectClass=inetOrgPerson)` | obrigatórias com `LDAP_URL`. No AD, o filtro inclui a conta habilitada: `(&(objectCategory=person)(!(userAccountControl:1.2.840.113556.1.4.803:=2)))` (D004-10) | R1.4, R1.6 |
| `LDAP_GROUP_BASE` / `LDAP_GROUP_FILTER` | `ou=grupos,...` / `(objectClass=groupOfNames)` | obrigatórias com `LDAP_URL` | R1.4, R1.8 |
| `LDAP_ATTR_LOGIN`, `LDAP_ATTR_EMAIL`, `LDAP_ATTR_NAME`, `LDAP_ATTR_ID`, `LDAP_ATTR_MEMBER` | `uid`, `mail`, `cn`, `entryUUID`, `member` (AD: `sAMAccountName`, `mail`, `displayName`, `objectGUID`, `member`) | nomes de atributo (`^[A-Za-z][A-Za-z0-9-]{0,63}$`); `LDAP_ATTR_ID` vazio usa o DN | R1.4, R1.5 |
| `LDAP_PAGE_SIZE` | `500` | 1 a 1000 | R1.4 |
| `LDAP_SYNC_CRON` | `30 2 * * *` | opcional; subconjunto de cron (§ Agendamento) | R1.12 |
| `OIDC_ISSUER` | `https://keycloak.localhost/realms/sgs` | `https://`; comparado byte a byte com o `iss` | R3.2 |
| `OIDC_DISCOVERY_URL` | `https://keycloak:8443/realms/sgs/.well-known/openid-configuration` | opcional; padrão `{OIDC_ISSUER}/.well-known/openid-configuration`; `https://` | R3.2 |
| `OIDC_CA_FILE` | `/certs-servicos/ca.crt` | opcional; sem ela, as CAs do sistema | R3.2 |
| `OIDC_CLIENT_ID` / `OIDC_CLIENT_SECRET` | `sgs-api` / `sgs-lab-exemplo-oidc` | obrigatórias com `OIDC_ISSUER`; em `prod`, segredo de exemplo recusado | R3.1, R5.4 |
| `OIDC_REDIRECT_URI` | `https://localhost/api/v1/auth/oidc/callback` | obrigatória com `OIDC_ISSUER`; `https://`; caminho igual a `/api/v1/auth/oidc/callback`; mesma origem de `FRONTEND_URL` (§ Decisões de execução) | R3.8 |
| `FRONTEND_URL` | `https://localhost/` | obrigatória com `OIDC_ISSUER`; `https://`, terminada em `/`, sem query nem fragmento; a origem dela tem de estar em `CORS_ORIGINS` (o front renova a sessão dali) | R3.8, R3.9 |
| `OIDC_GROUPS_CLAIM` | `groups` | — | R3.3 |
| `OIDC_REQUIRED_ACR` | vazio | opcional; lista separada por vírgula dos `acr` aceitos; vai também em `acr_values` no pedido | R3.6 |

- **Segredos de exemplo em `prod` (R5.4).** A regra é a mesma de `DATABASE_URL` (001/R2.3): `_uses_example_password`, isto é, `EXAMPLE_PASSWORDS` ou marcador de exemplo, aplicada a `LDAP_BIND_PASSWORD` e `OIDC_CLIENT_SECRET`. Os segredos do laboratório têm o marcador `exemplo` no valor (D004-15).
- O escopo OIDC pedido é fixo: `openid profile email`.
- O `.env.example` troca o bloco "variáveis reservadas" pelos valores do laboratório. A `steering/tech.md` não muda.

## Fluxo

### Sincronização (R1.1–R1.11, R4.2)
1. **Rota** (transação A). Grava a execução `em_andamento` com `triggered_by` e confirma. Se o índice único parcial recusar, responde 409 (R1.11). Sem `LDAP_URL`, responde 503. Responde 202 e agenda a tarefa em `BackgroundTasks` (R1.1).
2. **Leitura**, fora de transação. `await diretorio.snapshot()` lê todos os usuários e grupos (volume esperado: milhares). Se der `DirectoryUnavailable`, inclusive por certificado recusado, vai ao passo 5 sem ter tocado em dado local (R1.10, R1.13).
3. **Aplicação** (transação B, uma só):
   1. carrega os usuários e grupos `ldap` locais;
   2. `planejar(...)`;
   3. *upsert* de usuários por (`ldap`, `external_id`): cria os novos (R1.5); atualiza nome, e-mail e `is_active = true` dos encontrados; grava `synced_at` em todos (R1.6);
   4. desativa os usuários `ldap` que não vieram na busca, sem apagar (R1.7);
   5. *upsert* de grupos e desativação dos ausentes;
   6. troca as linhas `user_groups` de origem `ldap` dos usuários afetados (R1.8);
   7. para cada usuário cujo conjunto de grupos mudou, e para cada desativado (com grupos vazios), chama `recalcular_derivadas_do_usuario` (R1.8; 003/R3.2);
   8. fecha a execução `concluida` com as contagens e audita `diretorio.sincronizado` (R1.9).
4. **Conflitos** (R4.2). O usuário do diretório que seria criado com um `email` ou `username` já usado por outra conta não é criado nem unido a ela:
   - vira um item em `conflicts` (`tipo`, `external_id`, `usuario_existente_id`);
   - gera um evento `diretorio.conflito` (resultado `denied`);
   - os demais usuários seguem.

   Na atualização, um e-mail novo que colida mantém o e-mail antigo e também vira conflito.
5. **Falha** (transação C). Qualquer exceção no passo 2 ou 3 desfaz a transação B. A execução vira `falhou` com mensagem genérica ("Diretório indisponível" ou "Falha na sincronização"). `diretorio.sincronizado` é auditado com resultado `failure`, e o detalhe vai só para o log (R1.10).
6. **Execução interrompida.** Na subida (lifespan), execuções `em_andamento` viram `falhou` com "Interrompida". A API roda numa instância só (§ Riscos).

Quem dispara: o Admin TI pela rota (ator `usuario`, origem `api`) ou o agendador (ator `sistema`, origem `agendador`). O status de uma conta LDAP é "aparecer na busca filtrada" (D004-10); a sincronização é a fonte desse status e pode reativar uma conta que ela mesma desativou.

### Agendamento (R1.12)
- Com `LDAP_SYNC_CRON`, o lifespan inicia uma tarefa `asyncio`. Ela calcula o próximo horário no fuso de Recife (`src/core/fuso.py`), dorme até ele e dispara a sincronização pelo mesmo caso de uso. Se já houver execução em andamento, registra no log e pula. A tarefa é cancelada no desligamento.
- O subconjunto de cron aceito:
  - cinco campos;
  - minuto e hora aceitam número, `*`, `*/n` e lista `a,b`;
  - dia, mês e dia da semana só `*`.

  Outra forma é recusada na subida com mensagem clara (D004-9). O analisador é função pura no domínio.

### Login LDAP (R2, R4.1, R4.3, R4.4)
`LoginIn` ganha `provider: Literal["local", "ldap"] = "local"`. Com `"local"`, nada muda, inclusive a recusa de conta não local (R4.1). Com `"ldap"`, entra `entrar_por_ldap` (`identity/application/login_ldap.py`), na transação da rota, devolvendo `Falha` como o login local:

1. Senha vazia: `Falha` antes de qualquer chamada ao diretório (R2.4).
2. Conta local com esse `username`:
   - de outra origem: `Falha` (R4.1, simétrico);
   - bloqueada: `Falha` sem *bind*, para não martelar o diretório.
3. `find_user(username)` com a conta de serviço e filtro escapado (R2.2). Sem resultado: `Falha`, que soma falha se houver conta local.
4. `verify_password(dn, senha)`, um *bind* com o DN (R2.1). Senha errada: `registrar_falha` (5 seguidas bloqueiam 15 min, 002/R1.4) e `Falha`.
5. Conta local por (`ldap`, `external_id`):
   - inativa: `Falha`, sem reativar (R4.4);
   - inexistente: se o `email` ou o `username` já pertencem a outra conta, `Falha` genérica e `auth.login_failed` com `motivo = "conflito_de_conta"` (R4.3); senão, cria a conta e audita `usuario.provisionado`;
   - existente: atualiza nome, e-mail e `synced_at` (R2.3).
6. `groups_of(usuario)` → *upsert* de grupos, troca de `user_groups` `ldap` do usuário, `recalcular_derivadas_do_usuario` (R2.3).
7. `registrar_sucesso` e desafio do 2FA, igual ao local (R2.3). `_concluir_mfa` passa a escolher o `amr` pela origem da conta: `ldap+otp` para `ldap`, `pwd+otp` para `local` (D004-16).

`DirectoryUnavailable` em qualquer passo: `Falha` com status 503 ("Serviço de diretório indisponível") e auditoria `auth.login_failed` com `motivo = "diretorio_indisponivel"`. `Falha` ganha o status 503; a rota converte com uma subclasse nova `ServiceUnavailable(AppError)` (503) em `src/core/errors.py`. Os motivos de auditoria são uma lista fechada; a mensagem ao cliente continua a mesma da 002 nos casos 401.

### Login OIDC (R3, R4.3, R4.4)
**Início, `GET /auth/oidc/login`** (R3.1, R3.8):
1. Gera, com `secrets`, `state` (32 bytes), `nonce` (32 bytes), `code_verifier` (64 caracteres) e o valor do cookie de vínculo (32 bytes). O `code_challenge` S256 é calculado no domínio.
2. Grava em `oidc_login_requests` os hashes do `state` e do vínculo, o `nonce`, o `code_verifier` cifrado e `expires_at = agora + 10 min`. Apaga as linhas vencidas há mais de um dia.
3. Responde 302 para `authorization_url(...)`, com `redirect_uri = OIDC_REDIRECT_URI` vindo da configuração (R3.8), e grava o cookie `sgs_oidc=<vínculo>; HttpOnly; Secure; SameSite=Lax; Path=/api/v1/auth/oidc; Max-Age=600`. `SameSite=Lax` porque o retorno do provedor é uma navegação de nível superior entre sites. Cabeçalhos `Cache-Control: no-store` e `Referrer-Policy: no-referrer`.

**Callback, `GET /auth/oidc/callback`** (R3.2–R3.7):
1. **Consumo do `state`**, numa transação própria, confirmada antes de qualquer outro passo:
   - `UPDATE oidc_login_requests SET used_at = agora WHERE state_hash = :h AND used_at IS NULL AND expires_at > agora RETURNING ...`;
   - sem linha (repetido, vencido ou desconhecido): `motivo = "state"` (R3.7);
   - vínculo do cookie diferente: `motivo = "vinculo"`; o `state` já ficou usado.

   Confirmar antes impede que uma falha depois reabra o `state`.
2. `error` na query: `motivo = "erro_do_provedor"`.
3. `exchange(code, code_verifier, nonce)` (R3.2, R3.6). `OidcRejected.motivo` é um de: `troca`, `assinatura`, `iss`, `aud`, `exp`, `nonce`, `acr`, `claims`. `claims` cobre `preferred_username` ausente ou longo demais e claim de grupos que não é lista de textos.
4. **Provisionamento** (transação 2), por (`oidc`, `sub`):
   - conta inativa: `motivo = "desativado"`, sem reativar (R4.4);
   - conta inexistente, com `email` ou `username` já de outra conta: `motivo = "conflito_de_conta"` (R4.3);
   - senão, cria ou atualiza a conta (R3.3);
   - grupos: *upsert* dos grupos `oidc` da claim (até 200, cada um até 255 caracteres; o `external_id` e o nome são o valor da claim) e troca de `user_groups` `oidc`;
   - `recalcular_derivadas_do_usuario`;
   - `_abrir_sessao(amr="oidc")`: sem TOTP da API, porque no OIDC o segundo fator é do provedor (ADR-0003; R3.6 para exigir).
5. **Resposta de sucesso** (R3.4):
   - 302 para `FRONTEND_URL`;
   - `Set-Cookie` do `sgs_refresh`, como `_com_cookie`, mas sem o access token, que não sai da API;
   - apaga o `sgs_oidc`.

   Nenhum token vai na URL. O front abre a sessão pelo refresh (§ Front-end).
6. **Resposta de falha**, em qualquer motivo dos passos 1 a 4 (R3.5):
   - audita `auth.oidc_failed` com resultado `failure`, `motivo` e o `sub` quando houver (nunca o token nem o código), numa transação própria se a 2 tiver sido desfeita;
   - apaga o `sgs_oidc`;
   - responde 302 para `FRONTEND_URL?login_erro=oidc`.

   O código é um só, genérico.

## Front-end (R3.9)
Tarefa desta spec, por decisão do G1. Depois do G2, a 012 recebe só uma nota de referência no design § Abertura, apontando para esta seção, sem mudar o status nem o texto normativo dela, como a 013 fez com a 001 e a 011.

- `views/login.js`: ao desenhar a tela, chama `GET /api/v1/auth/provedores` uma vez. Com `oidc = true`, mostra abaixo do formulário um link-botão "Entrar pelo provedor de identidade" (`<a class="btn" href="/api/v1/auth/oidc/login">`). É navegação comum: a CSP atual (`default-src 'self'`, `form-action 'self'`) não muda.
- `main.js`, na abertura: se a URL tem `login_erro=oidc`, tira o parâmetro (`history.replaceState`) e mostra o login com "Não foi possível entrar pelo provedor de identidade. Tente de novo." No sucesso, o refresh silencioso que já existe abre a sessão. O cookie chegou no 302 do callback e é enviado no `fetch` de mesmo site para `/api/v1/auth/refresh`.
- A escolha de LDAP na tela não está na R3.9 e fica fora: o login LDAP é demonstrado pela API (`/docs`) e pelo teste ponta a ponta (§ Pontos para o G2).

## Ambiente de demonstração (R5)

### Certificados: `servicos-certs` (compartilhado com a 005)
- Serviço *one-shot* novo, no padrão do `db-certs` (`docker/servicos/gerar-certificados.sh`, `alpine:3.23`):
  - gera, se faltarem, uma CA de laboratório própria e certificados de servidor para `ldap`, `keycloak` e `s3`;
  - a chave da CA some no fim; nada vai para o Git;
  - o volume `servicos-certs` tem `ca/ca.crt` e `<serviço>/server.{crt,key}`, e cada serviço monta só a sua parte por `subpath`;
  - cada chave tem o dono do usuário do contêiner, como o `999` do PostgreSQL;
  - `openssl verify -x509_strict`, a mesma exigência do Python 3.13.
- O `db-certs` não muda (D004-8). Os três nomes saem de uma vez: a T8 que vier primeiro, desta spec ou da 005, cria o serviço.

### Redes
| Rede | Membros | Para quê |
|---|---|---|
| `borda` (existe) | proxy, api | Como hoje. O proxy só fala com a API por ela (IP fixo, 013/T4) |
| `dados` (existe) | api, db | Como hoje |
| `integracoes` (nova, `internal: true`) | api, ldap, keycloak (e `s3`, na 005) | LDAPS, *backchannel* OIDC, envio ao S3 |
| `exposicao` (nova) | proxy, keycloak (e `s3`, na 005) | Navegador → Keycloak (e S3) pelo Caddy |

Proxy e API não ganham outra rede em comum. Se ganhassem, o Caddy poderia chegar à API por um IP que não é o `/32` confiável (013/R3.1).

### `slapd` (R5.1)
- `docker/ldap/Dockerfile`: Debian estável + `slapd` + `ldap-utils`, uid fixo do usuário `openldap`.
- Escuta só `ldaps:///` (porta 636) e `ldapi:///`, este para a carga inicial e as alterações do roteiro. TLS 1.2 ou maior (`olcTLSProtocolMin 3.3`), certificado do `servicos-certs`.
- A carga inicial (`docker/ldap/seed.ldif`) roda na primeira subida:
  - `ou=pessoas`, `ou=grupos`, `ou=servicos`;
  - a conta de serviço `cn=sgs-sync`, só leitura por ACL;
  - um usuário por papel da 003 (`ADMIN_TI`, `GESTOR_DADOS`, `COORD_TECNICO`, `TECNICO_DISTRITAL`, `GESTOR_UNIDADE`, `DIRETORIA`, `AUDITOR`);
  - um usuário a mais para a demonstração da desativação;
  - grupos `groupOfNames` com nomes que digam o papel e o escopo (por exemplo, `sgs-tecnico-ds3`).
- As senhas do laboratório são fixas, versionadas, guardadas com hash `{SSHA}` no LDIF e listadas no roteiro (D004-15).
- Sem porta publicada no host. Um *alias* de rede a mais, `ldap-nome-errado`, serve só ao teste da R1.13.

### Keycloak (R5.2)
- Imagem `quay.io/keycloak/keycloak` com tag de versão estável fixada na T8 (nunca `latest`), em `start-dev --import-realm`.
- HTTPS 8443 com o certificado do `servicos-certs` (`KC_HTTPS_CERTIFICATE_FILE` e `KEY_FILE`, `KC_HTTP_ENABLED=false`).
- `KC_HOSTNAME=${SGS_PUBLIC_KEYCLOAK_URL:-https://keycloak.localhost}`, `KC_HOSTNAME_BACKCHANNEL_DYNAMIC=true` e `KC_PROXY_HEADERS=xforwarded`. O efeito:
  - o `iss` e o endpoint de autorização usam o endereço público, que o navegador alcança pelo Caddy;
  - a descoberta, o JWKS e o token, pedidos pela API em `https://keycloak:8443`, voltam com endereços internos.

  O `iss` tem de ser o mesmo nos dois caminhos; isso é conferido na primeira hora da T8 (§ Riscos).
- `docker/keycloak/realm-sgs.json` (realm `sgs`):
  - usuários e grupos próprios, sem federação com o `slapd` (G1; D004-7): um usuário por papel, com `username` e e-mail diferentes dos do LDIF e `emailVerified = true`;
  - cliente `sgs-api` confidencial, só *standard flow*, PKCE `S256` obrigatório, *redirect URI* exata `${SGS_PUBLIC_URL}/api/v1/auth/oidc/callback`, sem *direct access grants* nem *implicit*;
  - *mapper* "Group Membership" na claim `groups`, sem caminho completo, no `id_token`;
  - segredo `sgs-lab-exemplo-oidc`.
- Administrador de bootstrap só para o laboratório (`KC_BOOTSTRAP_ADMIN_*`, com marcador `exemplo`).

### Caddy e compose
- Bloco novo `keycloak.localhost` com `tls internal` e `reverse_proxy https://keycloak:8443`. O transporte confere o certificado pela CA de laboratório (`tls_trusted_ca_certs`, `tls_server_name keycloak`). A CA vem montada do `servicos-certs` só com `ca/`.
- O bloco `localhost` não muda: `/api/*` continua indo à API.
- Variáveis de compose com padrão: `SGS_PUBLIC_URL` (`https://localhost`) e `SGS_PUBLIC_KEYCLOAK_URL` (`https://keycloak.localhost`). Elas alimentam ao mesmo tempo o Keycloak (`KC_HOSTNAME`, *redirect URI*) e a API (`OIDC_ISSUER`, `OIDC_REDIRECT_URI`, `FRONTEND_URL`), para não haver duas fontes. Quem muda `SGS_HTTPS_PORT` muda essas também (README).
- A API não depende do `ldap` nem do `keycloak` para ficar saudável: o diretório e o provedor só são chamados no uso, e o `/health/ready` continua só com o banco.
- `docker/compose.test.yml`: os testes de integração não usam esses serviços (§ Estratégia de testes).

### Roteiro e ferramenta (R5.3)
- `docs/operacao/demo-diretorio.md`, passo a passo com os comandos:
  1. sincronizar e ver a execução;
  2. alterar e apagar um usuário no `slapd` (`docker compose exec ldap ldapmodify`/`ldapdelete` por `ldapi`) e sincronizar de novo;
  3. mapear um grupo pela 003;
  4. login LDAP com 2FA;
  5. login OIDC pela tela;
  6. recusa de certificado.
- `sgs-admin diretorio testar [--url URL] [--ca ARQUIVO]` tenta a conexão e o *bind* da conta de serviço com a configuração atual, ou com os valores dados, e não grava nada. Responde "ok" ou o motivo genérico (certificado, conexão, credencial). Serve ao operador e ao teste da R1.13 dentro da rede `integracoes`.

## Segurança
- **Transporte.** LDAPS ou StartTLS antes do *bind*, com CA e nome conferidos (R1.2, R1.13). HTTPS com CA conferida até o Keycloak, pela API e pelo Caddy.
- **Conta de serviço.** Só leitura (ACL no `slapd`; documentar o equivalente no AD). Senha só em `LDAP_BIND_PASSWORD`, nunca em log.
- **Injeção LDAP.** Todo valor de filtro passa por `escape_filter_chars` (R2.2; checklist de PR). DN do usuário só vem da busca, nunca da requisição.
- **OIDC:**
  - PKCE S256, `state` de uso único preso ao navegador, `nonce`, algoritmos fixos (nunca `none` nem `HS*`) e validação completa do `id_token` (R3.1, R3.2, R3.7);
  - `redirect_uri` e destino só da configuração, sem redirecionamento aberto (R3.8);
  - nenhum token na URL (R3.4).
- **Contas.**
  - Nada é unido automaticamente (R4.2, R4.3).
  - Login nunca reativa (R4.4).
  - Senha local nunca vale para conta externa (R4.1).
  - E-mail do OIDC só se verificado (D004-12).
- **Bloqueio.** As 5 falhas da 002 valem para conta LDAP local e são conferidas antes do *bind*. O limite por IP de `/auth/login` continua.
- **Auditoria** na transação do caso de uso:
  - `diretorio.sincronizado` (success/failure), `diretorio.conflito`, `usuario.provisionado`;
  - `auth.login` (com `amr`), `auth.login_failed`, `auth.oidc_failed`;
  - os `papel.atribuido` e `papel.removido` do recálculo, pela 003.

  Os motivos são de lista fechada, sem senha, código, token ou e-mail.
- **Segredos de laboratório.** Marcados com `exemplo` e recusados em `prod` (R5.4).
- **Checklist de PR.** As rotas novas declaram permissão ou estão em `PUBLICAS` com justificativa. A listagem de grupos é global (só `ADMIN_TI`). Há testes 401, 403 e 422.

## Decisões e alternativas
| Id | Decisão | Alternativas e por que não |
|---|---|---|
| D004-1 | Uma execução por vez por índice único parcial (`status = 'em_andamento'`), com recuperação na subida | `pg_advisory_lock` (rascunho anterior): a trava é da sessão do banco e não atravessa da requisição para a tarefa em segundo plano; segurar a conexão durante a leitura do diretório prenderia o pool |
| D004-2 | Estado OIDC no banco, com uso único por `UPDATE ... WHERE used_at IS NULL`, e cookie de vínculo | Cookie cifrado com `state`, `nonce` e `verifier` (rascunho anterior): não há como saber que um `state` já foi usado (R3.7) sem guardar algo no servidor |
| D004-3 | `id_token` conferido com o PyJWT; Authlib só para a URL de autorização e a troca do código | `authlib.jose`: a Authlib vem movendo a JOSE para o pacote `joserfc`, fora da stack; o PyJWT já assina e confere os tokens da API, com testes |
| D004-4 | `httpx` passa a dependência de execução, para o cliente assíncrono da Authlib. **Emenda 2 do ADR-0007, proposta** | Cliente `requests` da Authlib: bloqueante e também fora da stack. `urllib` à mão: reimplementa timeout, TLS e formulário |
| D004-5 | Callback abre a sessão só com o cookie de refresh; o front pega o access token pela renovação | Token no fragmento (`#`): proibido pela R3.4. Código próprio de uso único trocado pelo front: mais uma rota e um estado sem ganho, porque a renovação já existe |
| D004-6 | Listagem de grupos com `papel:assign` | `diretorio:sync`: quem precisa do `grupo_id` é quem mapeia (003/R3.1); os dois são só do `ADMIN_TI` hoje |
| D004-7 | Realm do laboratório sem federação (G1) | Federação com o mesmo `slapd`: toda pessoa sincronizada teria o login OIDC recusado pela R4.3 (e-mail único) |
| D004-8 | `servicos-certs` com CA própria, separado do `db-certs` | Estender o `db-certs`: a chave da CA é descartada, então um volume existente não ganharia certificados novos sem apagar o do banco |
| D004-9 | Agendador próprio (`asyncio` no lifespan) com subconjunto de cron | APScheduler ou `croniter`: fora da stack (exigiriam ADR) para uma tarefa diária |
| D004-10 | Status da conta LDAP = aparecer na busca filtrada; no AD, o filtro inclui "conta habilitada" | Variável a mais para atributo de status: o AD e o OpenLDAP não têm um atributo comum, e o filtro já resolve |
| D004-11 | Conflito também por `username` (único em todas as origens) | Prefixar o `username` externo: mudaria o login que a pessoa digita |
| D004-12 | E-mail do OIDC só com `email_verified = true` | Aceitar qualquer e-mail: um e-mail não verificado poderia tomar o lugar de outro e provocar conflito (R4.3) |
| D004-13 | Redes `integracoes` e `exposicao`, sem nova rede comum entre proxy e API | Uma rede só para tudo: o Caddy poderia chegar à API por outro IP (013/R3.1) |
| D004-14 | Keycloak e S3 em hosts próprios (`keycloak.localhost`, `s3.localhost`) na mesma porta do Caddy | Prefixo de caminho: muda o caminho assinado da URL do S3 e os caminhos do Keycloak. Porta própria: mais uma porta no host |
| D004-15 | Segredos e senhas do laboratório fixos e versionados, com o marcador `exemplo` | Gerados na subida: quem apresenta precisa saber as senhas, e a recusa em `prod` (R5.4) depende de reconhecê-las |
| D004-16 | `amr` do 2FA pela origem da conta (`ldap+otp`) | Guardar a origem no `mfa_token`: a conta já diz |

## Riscos
| Risco | Mitigação |
|---|---|
| `ldap3` 2.9.1 sem release desde 2021; a conferência de nome usa o *backport* da própria biblioteca no Python 3.13 | Teste da R1.13 com servidor TLS local (CA errada e nome errado) roda no `make check`; se falhar, o adaptador passa um `ssl.SSLContext` com `check_hostname` |
| `iss` diferente entre o navegador e a API no Keycloak | Conferir na primeira hora da T8; a alternativa é a API usar o endereço público com resolução para o Caddy na rede `integracoes`, registrada aqui antes de seguir |
| Navegador não guardar o cookie `SameSite=Strict` recebido no fim de um redirecionamento entre sites | O teste ponta a ponta com navegador cobre o fluxo inteiro; a alternativa é o callback responder uma página mínima que navega para o front |
| 003/T8 fora da `main` | O recálculo depende dela: a T3, a T5 e a T7 ficam bloqueadas até o porte (§ Pontos para o G2) |
| Keycloak pesado (memória e uns 30 s de subida) no compose e no *smoke* do CI | A API não depende dele para ficar saudável; o tempo do `--wait` aumenta e fica registrado no README |
| Bloqueio de conta no AD por *binds* errados | O bloqueio local (5 falhas) corta antes do *bind*; os limites do AD costumam ser maiores |
| Uma instância só da API (agendador, tarefas em segundo plano, recuperação na subida) | É o desenho do projeto (arquitetura § worker); mais de uma instância exige fila, fora do escopo |
| Diretório real com `username` ou e-mail iguais aos de contas locais | Viram conflitos visíveis na execução, sem bloquear os demais |
| Chave removida ou revogada no provedor continua aceita: o JWKS em cache só recarrega com `kid` desconhecido | Risco aceito até a SR2 (§ Decisões de execução): depois de remover ou revogar uma chave no provedor, reinicie a API. Validade do cache fica para depois da SR2 |

## Estratégia de testes
Todo teste cita o critério na docstring (`"""004/R1.7"""`). Sem internet: o LDAP é `MOCK_SYNC` ou um servidor TLS local, o OIDC é um provedor falso com JWKS gerado no teste.

| Nível | Arquivo | O que prova | Requisitos |
|---|---|---|---|
| Unidade | `tests/unit/identity/test_plano_sincronizacao.py` | `planejar`: criar, atualizar, desativar, reativar, grupos, associações, conflito de e-mail e de `username` | R1.5–R1.8, R4.2 |
| Unidade | `tests/unit/identity/test_ldap3_adapter.py` | `MOCK_SYNC` com LDIF de teste: paginação, só atributos configurados, `find_user`, `verify_password`, senha vazia sem *bind*, entradas maliciosas (`*)(uid=*`) com `hypothesis` | R1.4, R2.1, R2.2, R2.4 |
| Unidade | `tests/unit/identity/test_oidc_validacao.py` | `id_token` gerado no teste: assinatura, `iss`, `aud`/`azp`, `exp`, `nonce`, `alg` `none`/`HS256` recusados, `kid` desconhecido recarrega uma vez, `acr` | R3.2, R3.6 |
| Unidade | `tests/unit/identity/test_cron.py` | Subconjunto aceito, formas recusadas, próximo horário no fuso de Recife | R1.12 |
| Unidade | `tests/unit/core/test_config.py` | `ldap://` sem StartTLS recusado; OIDC incompleto; `FRONTEND_URL` fora de `CORS_ORIGINS`; segredos do laboratório recusados em `prod` | R1.2, R3.8, R5.4 |
| Integração | `tests/integration/identity/test_directory_tables.py` | Tabelas, restrições, índice único parcial, FK de `group_role_mappings` | R1.9, R1.11, R1.14 |
| Integração | `tests/integration/identity/test_ldap_tls.py` | Servidor TLS local em *thread*: CA errada e nome errado recusados, sem nenhum byte LDAP enviado (nenhuma credencial) | R1.2, R1.13 |
| Integração | `tests/integration/identity/test_ldap_sync.py` | Caso de uso com `DirectoryPort` falso e Postgres: criação, atualização, desativação, grupos, recálculo da 003, auditoria, falha sem alterar nada | R1.5–R1.10, R4.2 |
| Integração | `tests/integration/identity/test_sync_routes.py` | 202, 409 em andamento, 503 sem LDAP, execuções, listagem de grupos com membros ativos; 401, 403, 422 | R1.1, R1.9, R1.11, R1.14 |
| Integração | `tests/integration/identity/test_sync_schedule.py` | Agendador com relógio e espera falsos; execução pulada se já houver uma | R1.12 |
| Integração | `tests/integration/identity/test_ldap_login.py` | *Bind*, provisionamento, grupos, 2FA com `amr = ldap+otp`, bloqueio, conta de outra origem, conflito, conta inativa, diretório fora (503) | R2.1–R2.4, R4.1, R4.3, R4.4 |
| Integração | `tests/integration/identity/test_oidc_callback.py` | Provedor falso (`httpx.MockTransport`): início com cookie e `redirect_uri` da configuração; callback com sucesso (cookie de refresh, 302, sem token na URL); `state` repetido, vencido e de outro navegador; erro do provedor; conflito; conta inativa | R3.1–R3.5, R3.7, R3.8, R4.3, R4.4 |
| Arquitetura | `tests/architecture/test_rotas_protegidas.py` | Rotas novas protegidas ou em `PUBLICAS` | — |
| Front | `tests/e2e_front/test_login_oidc.py` | Playwright (ADR-0011) com a API simulada (`page.route`): botão só com `oidc = true`; mensagem com `login_erro=oidc` e URL limpa | R3.9 |
| Ponta a ponta (`slow`) | `tests/e2e/test_sync_ldap.py` | Compose real: sincronização cria, atualiza e desativa; `sgs-admin diretorio testar` recusa a CA do banco e o *alias* `ldap-nome-errado` | R5.1, R5.3, R1.13 |
| Ponta a ponta (`slow`) | `tests/e2e/test_login_ldap_oidc.py` | Login LDAP com cadastro e verificação do TOTP (`pyotp`); login OIDC pelo navegador (tela do front → Keycloak → front com sessão aberta e `/me`) | R5.2, R5.3, R3.9 |

## Cobertura dos requisitos
| Requisito | Seções |
|---|---|
| R1.1 | Rotas; Fluxo § Sincronização (1) |
| R1.2 | Portas e adaptadores (`ldap3_directory`); Configuração; Segurança |
| R1.3 | Configuração (`LDAP_BIND_*`); Ambiente § `slapd` (ACL) |
| R1.4 | Portas e adaptadores (busca paginada, atributos) |
| R1.5–R1.8 | Fluxo § Sincronização (3); Modelo de dados |
| R1.9 | Rotas (`Execucao`); Modelo de dados; Fluxo § Sincronização (3.8) |
| R1.10 | Fluxo § Sincronização (2 e 5) |
| R1.11 | Modelo de dados (índice parcial); Rotas (409); D004-1 |
| R1.12 | Fluxo § Agendamento; D004-9 |
| R1.13 | Portas e adaptadores; Ambiente (`ldap-nome-errado`, `sgs-admin diretorio testar`); Testes |
| R1.14 | Rotas (`/grupos`); Modelo de dados; D004-6 |
| R2.1–R2.4 | Fluxo § Login LDAP; Portas e adaptadores |
| R3.1 | Fluxo § Login OIDC (início) |
| R3.2 | Portas e adaptadores (`authlib_oidc`); Fluxo § Login OIDC (callback, 3) |
| R3.3 | Fluxo § Login OIDC (callback, 4) |
| R3.4 | Fluxo § Login OIDC (callback, 5); D004-5 |
| R3.5 | Fluxo § Login OIDC (callback, 6) |
| R3.6 | Configuração (`OIDC_REQUIRED_ACR`); Portas e adaptadores |
| R3.7 | Modelo de dados (`oidc_login_requests`); Fluxo § Login OIDC (callback, 1); D004-2 |
| R3.8 | Configuração (`OIDC_REDIRECT_URI`, `FRONTEND_URL`); Fluxo § Login OIDC (início) |
| R3.9 | Front-end; Rotas (`/auth/provedores`) |
| R4.1 | Fluxo § Login LDAP (passo 2); login local da 002 sem mudança |
| R4.2 | Fluxo § Sincronização (4); D004-11 |
| R4.3 | Fluxo § Login LDAP (passo 5) e § Login OIDC (callback, 4) |
| R4.4 | Idem |
| R5.1 | Ambiente § `slapd`, § Certificados, § Redes |
| R5.2 | Ambiente § Keycloak, § Caddy e compose |
| R5.3 | Ambiente § Roteiro e ferramenta; Testes ponta a ponta |
| R5.4 | Configuração (segredos de exemplo em `prod`); D004-15 |

Sem cobertura: nenhum.

## Pontos para o G2
1. **003/T8 na `main`.** O recálculo (R1.8, R2.3, R3.3) usa o contrato da 003/T8, que só existe na `origin/feat/011-integracao`. Recomendação: portar a 003/T8 para a `main` como primeira tarefa de código, antes da T3 desta spec. A 003 é do Vinicius; como responsável pelo projeto, o Rafael também pode fazer o porte, sem mudar o dono.
2. **Emenda 2 do ADR-0007** (`httpx` 0.28.x em execução, D004-4). Recomendação: aceitar junto com este G2.
3. **Escolha de LDAP na tela de login.** Fora da R3.9, e o texto atual da tela ("seu usuário e sua senha da Prefeitura") sugere credencial corporativa. Recomendação: manter fora (demonstração pela API e pelo teste ponta a ponta) e, se o grupo quiser na tela, abrir emenda da 012.
4. **Ainda abertas, sem bloquear:** AD ou OpenLDAP na Secretaria e o atributo de distrito ou unidade (requisitos, Perguntas em aberto). O design cobre os dois diretórios por configuração.

## Decisões do G2 (Rafael, 24/11/2026)
- O porte da 003/T8 para a `main` vem antes da sincronização (T3), do login LDAP (T5) e do callback (T7). É a primeira tarefa da frente A (`tasks.md`).
- A emenda 2 do ADR-0007 (httpx) passa a `Aceito`.
- A escolha de LDAP na tela de login fica fora desta spec. O login LDAP é demonstrado pela API e pelo teste ponta a ponta.
- O trabalho das specs 004 e 005 corre em três frentes simultâneas. A divisão e os pontos de encontro estão em `tasks.md` (G3).
- Continuam abertas, sem bloquear: AD ou OpenLDAP e o atributo de distrito ou unidade.

## Decisões de execução (Rafael, 25/11/2026)
Registro do agente por autorização expressa dada na sessão de trabalho, depois da revisão de código da 004/T6 e da 005/T9.
- **`OIDC_REDIRECT_URI` com a mesma origem de `FRONTEND_URL`** (§ Configuração). A API recusa a subida se as origens forem diferentes, em `_oidc_problems()`. Outra combinação não funciona: o link do front é relativo, então o login começa no host do front; o cookie `sgs_oidc` é desse host e não chega a um callback em outro; e o cookie de refresh gravado pelo callback ficaria num host de onde o front não renova a sessão. O compose já deriva os dois de `SGS_PUBLIC_URL` (§ Caddy e compose).
- **JWKS sem validade no cache, por enquanto** (§ Riscos). Fica a recarga por `kid` desconhecido, no máximo uma vez por minuto. Uma chave removida ou revogada no provedor continua aceita até a API reiniciar. Risco aceito até a SR2; a validade do cache volta a ser discutida depois dela.
- **Achados da revisão da frente A (26/11/2026, pedido do Helder, a confirmar com o Rafael).** S2: mapeamento com `grupo_id` inexistente responde 422 no campo. S4: o login LDAP e o OIDC gravam `usuario.atualizado` quando o diretório muda nome ou e-mail, só com os nomes dos campos. S5, critério mínimo: um retrato sem nenhum usuário, com contas LDAP ativas no banco, faz a execução falhar ("Diretório sem usuários; nada foi desativado") sem tocar em nada; um retrato pequeno, mas não vazio, ainda desativa quem ficou de fora.
