# ADR-0003: Identidade federada (LDAP/OIDC) com tokens próprios

- Status: Proposto
- Data: 2026-10-03
- Requisitos relacionados: RS-01, RS-02, requisito obrigatório de LDAP/OIDC

## Contexto
A API precisa aceitar três origens de identidade (local, LDAP e OIDC), popular tabelas locais de usuários e grupos e aplicar o mesmo RBAC a todas. A orientação de criptografia recomenda chaves assimétricas.

## Decisão
- Usuários e grupos externos são espelhados em `users`/`groups` com `source` e `external_id`. LDAP é sincronizado por job (busca paginada) e também aceito no login por bind; OIDC usa Authorization Code + PKCE com provisionamento just-in-time.
- Depois de autenticar por qualquer origem, a API emite **seus próprios** tokens: access JWT ES256 de 15 minutos e refresh opaco rotativo em cookie HttpOnly.
- Permissões não vão no JWT; são resolvidas no servidor a cada requisição.
- 2FA por TOTP para contas locais e LDAP; no OIDC, o 2FA é do provedor.

## Consequências
- O RBAC e a auditoria ficam idênticos para qualquer origem.
- Revogar um papel ou desativar um usuário tem efeito imediato.
- A API precisa gerenciar chaves de assinatura (rotação por `kid`, JWKS publicado).

## Alternativas consideradas
- Repassar o token do Keycloak para a API: acopla a API ao IdP e não cobre login LDAP direto nem contas locais.
- Sessão server-side com cookie em todas as rotas: exige proteção CSRF em toda a API.
