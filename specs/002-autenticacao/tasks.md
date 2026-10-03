# 002 · Autenticação · Tarefas

- Status: Aprovado (Leonardo, 03/10/2026)
- Depende de: 001

- [ ] T1. `FieldCipher` AES-256-GCM com chaves versionadas
  - Requisitos: R2.5
  - Pronto quando: `tests/unit/core/test_crypto.py` passa
- [ ] T2. Migração `0002_identity` e repositórios de usuário, sessão e refresh
  - Requisitos: R1.7, R3.3
  - Pronto quando: `tests/integration/identity/test_repositories.py` passa
- [ ] T3. `PasswordHasher` Argon2id e caso de uso de login com hash fictício e bloqueio
  - Requisitos: R1.1, R1.2, R1.3, R1.4, R1.6
  - Pronto quando: `tests/integration/identity/test_login.py` passa
- [ ] T4. `TokenService` ES256 + JWKS
  - Requisitos: R3.1, R3.2, R3.8
  - Pronto quando: `tests/unit/identity/test_tokens.py` passa
- [ ] T5. Cadastro e verificação de TOTP
  - Requisitos: R2.1–R2.6
  - Pronto quando: `tests/integration/identity/test_mfa.py` passa
- [ ] T6. Refresh rotativo com detecção de reuso, anti-CSRF e logout
  - Requisitos: R3.3–R3.7
  - Pronto quando: `tests/integration/identity/test_refresh.py` passa
- [ ] T7. Rate limit e auditoria dos eventos de acesso
  - Requisitos: R1.5, R4.1
  - Pronto quando: `tests/integration/identity/test_auth_audit.py` passa
- [ ] T8. Comando `sgs-admin create-user` para criar o primeiro administrador
  - Requisitos: R1.7
  - Pronto quando: comando documentado no README e coberto por teste
