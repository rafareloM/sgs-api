# 004 · Diretório LDAP e OIDC · Design

- Status: Rascunho

## Portas e adaptadores
```python
class DirectoryPort(Protocol):
    def iter_users(self) -> Iterator[DirectoryUser]: ...
    def iter_groups(self) -> Iterator[DirectoryGroup]: ...
    def find_user_dn(self, login: str) -> str | None: ...
    def verify_password(self, dn: str, password: str) -> bool: ...

class OidcPort(Protocol):
    async def authorization_url(self, redirect_uri: str) -> AuthRequest: ...
    async def exchange(self, code: str, auth_request: AuthRequest) -> OidcIdentity: ...
```
- `infrastructure/ldap3_directory.py`: implementação com `ldap3.Server(use_ssl=True, tls=Tls(validate=CERT_REQUIRED))`, `Connection(auto_bind=..., read_only=True)`, `extend.standard.paged_search`. Chamado pelo caso de uso via `anyio.to_thread.run_sync`.
- `infrastructure/authlib_oidc.py`: `authlib.integrations.httpx_client.AsyncOAuth2Client` com metadados da descoberta e validação de `id_token` via `authlib.jose` / JWKS em cache.

## Configuração
| Variável | Exemplo |
|---|---|
| `LDAP_URL` | `ldaps://ldap:636` |
| `LDAP_BIND_DN` / `LDAP_BIND_PASSWORD` | `cn=sgs-sync,ou=servicos,dc=recife,dc=pe,dc=gov,dc=br` |
| `LDAP_USER_BASE` / `LDAP_USER_FILTER` | `ou=pessoas,...` / `(objectClass=inetOrgPerson)` |
| `LDAP_GROUP_BASE` / `LDAP_GROUP_FILTER` | `ou=grupos,...` / `(objectClass=groupOfNames)` |
| `LDAP_ATTR_*` | `uid`, `mail`, `cn`, `entryUUID`, `member` (AD: `sAMAccountName`, `objectGUID`) |
| `LDAP_CA_FILE` | `/run/secrets/ldap-ca.pem` |
| `OIDC_ISSUER` | `https://keycloak.local/realms/sgs` |
| `OIDC_CLIENT_ID` / `OIDC_CLIENT_SECRET` | cliente confidencial `sgs-api` |
| `OIDC_GROUPS_CLAIM` | `groups` |
| `OIDC_REQUIRED_ACR` | opcional |

## Estado do fluxo OIDC
`state`, `nonce` e `code_verifier` ficam em cookie cifrado (AES-GCM, `HttpOnly`, `SameSite=Lax`, 10 min), porque o retorno do provedor é uma navegação cross-site.

## Sincronização (algoritmo)
1. Abre execução (`status = em_andamento`), com trava por `pg_advisory_lock` (R1.11).
2. Lê todos os usuários e grupos do diretório para memória (volume esperado: milhares, cabe).
3. Em uma transação: upsert de usuários por (`source`, `external_id`); desativa ausentes; upsert de grupos; substitui `user_groups` de origem `ldap`; recalcula atribuições derivadas (spec 003).
4. Fecha execução com contagens; audita.
5. Qualquer exceção antes do commit → rollback e `status = falhou` (R1.10).

## Ambiente de desenvolvimento
- `docker/ldap/`: Dockerfile Debian + `slapd`, LDIF com `ou=pessoas`, `ou=grupos`, `ou=servicos` e usuários de exemplo por perfil (um por papel), certificado gerado no build.
- `docker/keycloak/realm-sgs.json`: realm `sgs`, cliente `sgs-api` (confidencial, PKCE S256), *mapper* de grupos na claim `groups`, federação LDAP apontando para o mesmo `slapd`.

## Rotas
| Método e rota | Permissão | Requisitos |
|---|---|---|
| `POST /api/v1/admin/diretorio/sincronizar` | `diretorio:sync` | R1.1, R1.11 |
| `GET /api/v1/admin/diretorio/execucoes` · `/{id}` | `diretorio:sync` | R1.9 |
| `POST /api/v1/auth/login` com `provider=ldap` | pública | R2 |
| `GET /api/v1/auth/oidc/login` | pública | R3.1 |
| `GET /api/v1/auth/oidc/callback` | pública | R3.2–R3.5 |

## Estratégia de testes
- Unidade: sincronização com `ldap3` `MOCK_SYNC` carregado de um LDIF de teste (criar, atualizar, desativar, grupos); escape de filtro com entradas maliciosas (`*)(uid=*`).
- Unidade: OIDC com JWKS e `id_token` gerados no teste (nonce errado, `aud` errado, expirado).
- Integração (marcador `slow`): compose com `slapd` e Keycloak reais, login ponta a ponta.
