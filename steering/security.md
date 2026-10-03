# Steering · Segurança

Dados de saúde pública, LGPD e auditoria são o centro do produto. Na dúvida, escolha o mais restritivo e registre a dúvida na spec.

## Checklist para todo PR
- [ ] Rotas novas declaram permissão (`require`) ou estão na lista de públicas com justificativa.
- [ ] Listagens aplicam `scope_filter`.
- [ ] Alterações de negócio chamam `audit.registrar` na mesma transação.
- [ ] Entrada validada por schema Pydantic com limites (`max_length`, regex, enums).
- [ ] Nenhuma SQL montada com string; nenhum filtro LDAP sem `escape_filter_chars`.
- [ ] Nenhum segredo, token ou senha em log, exceção, resposta ou commit.
- [ ] Respostas de erro não expõem stack trace, SQL ou caminho interno.
- [ ] Dados sensíveis (segredo TOTP, tokens) cifrados com `FieldCipher`.
- [ ] Testes negativos: sem token (401), sem permissão (403), fora do escopo (403), entrada inválida (422).

## Autenticação
Argon2id; TOTP obrigatório para contas locais e LDAP; access JWT ES256 15 min; refresh opaco rotativo em cookie HttpOnly com detecção de reuso; anti-CSRF no refresh; rate limit e bloqueio após 5 falhas. Detalhes: `specs/002-autenticacao`.

## Autorização
RBAC com escopo, deny by default, permissões resolvidas no servidor a cada requisição, segregação de funções (Admin TI não edita cadastro; ninguém atribui papel a si mesmo). Detalhes: `specs/003-rbac`.

## Criptografia
- Trânsito: TLS 1.2+ em todos os enlaces (cliente↔proxy, API↔Postgres `verify-full`, LDAPS, HTTPS para S3 e OIDC).
- Repouso: volume criptografado; AES-256-GCM em campos sensíveis com nonce aleatório de 96 bits por gravação e versão de chave; SSE-KMS no S3.
- Assinatura: ES256 com `kid` e rotação.
- Nunca reutilizar nonce; nunca implementar primitiva criptográfica própria.

## Integrações
- LDAP: conta de serviço só leitura, TLS com validação de certificado, atributos explícitos.
- OIDC: Code + PKCE S256, `state` e `nonce`, validação completa do `id_token`.
- S3: sem chave fixa em prod (STS AssumeRole), bucket privado, URL pré-assinada de 5 min.

## LGPD
Não há dado de paciente no escopo. Dados de profissionais (gestor da unidade) são pessoais: exibir só a quem precisa, registrar acesso, não exportar além do necessário.

## Auditoria
`audit_log` append-only (trigger), hash encadeado, retenção de 2 anos, eventos de acesso e de alteração.
