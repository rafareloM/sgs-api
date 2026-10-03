# 002 · Autenticação · Requisitos

- Status: Aprovado (Rafael, 03/10/2026)
- Rastreia: RS-01, RS-03, RS-04, RS-05, RS-08, RS-09, critério 6.1 "login leva a tela coerente com o perfil"

## Contexto
Requisito obrigatório: "criar um sistema de autenticação e permissão de acesso". Esta spec cobre a autenticação (quem é você); a spec 003 cobre a permissão. A Atividade 5 decidiu entregar 2FA no MVP.

## Fora do escopo
- Login via LDAP e OIDC (spec 004), que reutiliza a emissão de tokens definida aqui.
- Recuperação de senha por e-mail (evolução; no MVP, o Admin TI redefine).
- 2FA por SMS.

## Histórias e critérios

### R1. Login com senha
Como usuário local, quero entrar com usuário e senha.

- R1.1 QUANDO usuário e senha estão corretos e o usuário tem 2FA ativo, o sistema DEVE responder `mfa_required: true` e um `mfa_token` válido por 5 minutos, sem emitir tokens de acesso.
- R1.2 QUANDO usuário e senha estão corretos e o 2FA ainda não foi cadastrado, o sistema DEVE responder `mfa_enrollment_required: true` e um `mfa_token` que só permite cadastrar o 2FA.
- R1.3 SE usuário ou senha estiverem errados, ENTÃO o sistema DEVE responder 401 com a mesma mensagem e tempo de resposta semelhante para usuário inexistente e senha errada.
- R1.4 SE houver 5 falhas seguidas para o mesmo usuário, ENTÃO o sistema DEVE bloquear o login desse usuário por 15 minutos.
- R1.5 O sistema DEVE limitar `POST /auth/login` a 10 requisições por minuto por IP.
- R1.6 SE o usuário estiver desativado, ENTÃO o sistema DEVE recusar o login com 401.
- R1.7 O sistema DEVE armazenar senhas apenas como hash Argon2id.

### R2. Segundo fator (TOTP)
- R2.1 QUANDO o usuário inicia o cadastro de 2FA, o sistema DEVE gerar um segredo TOTP e devolver a URI `otpauth://` (para QR code) uma única vez.
- R2.2 QUANDO o usuário confirma com um código válido, o sistema DEVE ativar o 2FA e emitir os tokens de acesso.
- R2.3 QUANDO o usuário envia `mfa_token` e código TOTP válido, o sistema DEVE emitir access token e refresh token.
- R2.4 O sistema DEVE aceitar códigos na janela de ±30 segundos e recusar o reuso do mesmo código.
- R2.5 O sistema DEVE guardar o segredo TOTP cifrado com AES-256-GCM.
- R2.6 SE houver 5 códigos errados para o mesmo `mfa_token`, ENTÃO o sistema DEVE invalidar esse `mfa_token`.

### R3. Tokens e sessão
- R3.1 O sistema DEVE emitir access token JWT assinado com ES256, validade de 15 minutos, contendo `sub`, `sid`, `iss`, `aud`, `iat`, `exp`, `amr` e `kid` no cabeçalho.
- R3.2 O sistema DEVE publicar as chaves públicas em `GET /.well-known/jwks.json`.
- R3.3 O sistema DEVE emitir refresh token opaco em cookie `HttpOnly; Secure; SameSite=Strict; Path=/api/v1/auth`, válido por 8 horas, e guardar só o seu hash.
- R3.4 QUANDO um refresh válido é usado, o sistema DEVE emitir um novo par e invalidar o refresh usado.
- R3.5 SE um refresh já usado for apresentado de novo, ENTÃO o sistema DEVE revogar a sessão inteira e auditar `auth.refresh_reuse`.
- R3.6 O sistema DEVE exigir o cabeçalho `X-Requested-With: sgs` e `Origin` permitida em `POST /auth/refresh` (anti-CSRF).
- R3.7 QUANDO o usuário faz logout, o sistema DEVE revogar a sessão e apagar o cookie.
- R3.8 SE o access token estiver expirado, com assinatura inválida, com `aud`/`iss` errados ou de sessão revogada, ENTÃO o sistema DEVE responder 401.

### R4. Auditoria de acesso
- R4.1 O sistema DEVE auditar `auth.login`, `auth.login_failed`, `auth.mfa_failed`, `auth.locked`, `auth.logout`, `auth.refresh_reuse` e `auth.mfa_enrolled`, com IP e user agent.

## Perguntas em aberto
- Validade de 8 h para a sessão é adequada à jornada da Secretaria?
