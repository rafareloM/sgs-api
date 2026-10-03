# 002 · Autenticação · Design

- Status: Aprovado (Leonardo, 03/10/2026)

## Rotas
| Método e rota | Acesso | Entrada | Saída | Erros | Requisitos |
|---|---|---|---|---|---|
| `POST /api/v1/auth/login` | pública, rate limit | `{username, password}` | `{mfa_required, mfa_enrollment_required, mfa_token}` | 401, 429 | R1.* |
| `POST /api/v1/auth/mfa/enroll` | `mfa_token` (finalidade `enroll`) | — | `{otpauth_uri}` | 401 | R2.1 |
| `POST /api/v1/auth/mfa/confirm` | `mfa_token` (`enroll`) | `{code}` | `{access_token, expires_in}` + cookie | 400, 401 | R2.2 |
| `POST /api/v1/auth/mfa/verify` | `mfa_token` (`verify`) | `{code}` | `{access_token, expires_in}` + cookie | 401 | R2.3–R2.6 |
| `POST /api/v1/auth/refresh` | cookie + `X-Requested-With` | — | `{access_token}` + cookie | 401, 403 | R3.4–R3.6 |
| `POST /api/v1/auth/logout` | Bearer | — | 204 | 401 | R3.7 |
| `GET /.well-known/jwks.json` | pública | — | JWKS | — | R3.2 |

## Componentes (`modules/identity`)
- `domain/passwords.py`: interface `PasswordHasher`; implementação `pwdlib` Argon2id em `infrastructure/`.
- `domain/tokens.py`: `TokenService` (emitir/validar JWT, emitir/validar `mfa_token` com claim `purpose`).
- `domain/totp.py`: wrapper de `pyotp` com registro do último passo usado (`users.mfa_last_step`) para impedir reuso.
- `core/crypto.py`: `FieldCipher` AES-256-GCM com chaves versionadas (`CRYPTO_KEYS='{"1":"base64..."}'`, `CRYPTO_ACTIVE_KEY=1`).
- `application/login.py`, `mfa.py`, `refresh.py`, `logout.py`: casos de uso.
- `api/deps.py`: `CurrentUser` (valida Bearer, carrega sessão ativa, usuário ativo).

## Chaves JWT
- Par EC P-256 em PEM via variável de ambiente ou arquivo montado (`JWT_PRIVATE_KEYS`, lista com `kid`). A chave ativa assina; todas as públicas são publicadas no JWKS, permitindo rotação sem derrubar sessões.
- `mfa_token` é um JWT curto, `aud = sgs-mfa`, com `purpose` e `jti` (para contar tentativas).

## Modelo de dados
Migração `0002_identity`: `users`, `sessions`, `refresh_tokens` (ver `docs/architecture/modelo-dados.md`), mais `users.mfa_last_step` e contadores de falha.

## Segurança
- Hash fictício para usuário inexistente (R1.3).
- Rate limit via slowapi com chave IP; bloqueio por usuário no banco (R1.4).
- Comparações de token com `hmac.compare_digest`.
- Nenhum token em log; cookies com `Secure` mesmo em dev (proxy TLS local).

## Decisões
- Permissões fora do token (ADR-0003).
- TOTP obrigatório para contas locais; pode ser desligado por configuração apenas em `dev` para acelerar testes manuais.

## Riscos
- Relógio do servidor fora de sincronia quebra TOTP: container usa NTP do host; janela ±1 passo.

## Estratégia de testes
- Unidade: hasher, TokenService (expiração, `aud`, `kid` desconhecido), FieldCipher (nonce único, troca de chave), TOTP (reuso).
- Integração: fluxo completo login → enroll → confirm → refresh → reuso → logout; bloqueio após 5 falhas; tempo de resposta semelhante (tolerância ampla).
- Segurança: teste que varre logs capturados procurando token/senha.
