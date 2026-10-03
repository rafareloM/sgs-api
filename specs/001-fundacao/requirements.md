# 001 · Fundação da API · Requisitos

- Status: Aprovado (Leonardo, 03/10/2026)
- Rastreia: RNF-01, RNF-06, RS-03, RS-05, RS-08, critério 6.1 "sobe em outra máquina"

## Contexto
Antes de qualquer funcionalidade, a API precisa de um esqueleto que já nasça com configuração por ambiente, banco com migrações, formato de erro único, logs estruturados, auditoria base e CI. Tudo o que vem depois se apoia nisso.

## Fora do escopo
- Autenticação (spec 002) e RBAC (spec 003).
- Deploy em nuvem.

## Histórias e critérios

### R1. Subir o ambiente
Como integrante do grupo, quero subir a API e suas dependências com um comando para desenvolver e demonstrar em qualquer máquina.

- R1.1 QUANDO alguém executa `docker compose up` seguindo o README, o sistema DEVE subir API, PostgreSQL e proxy TLS. LDAP, Keycloak e S3 local entram no compose nas specs 004 e 005.
- R1.2 O sistema DEVE aplicar as migrações do banco automaticamente na subida em `dev`.
- R1.3 O sistema DEVE responder `GET /health/live` com 200 sempre que o processo estiver no ar.
- R1.4 QUANDO o banco estiver inacessível, o sistema DEVE responder `GET /health/ready` com 503.

### R2. Configuração por ambiente
- R2.1 O sistema DEVE ler toda configuração de variáveis de ambiente validadas na inicialização (`APP_ENV` = `dev`, `test` ou `prod`).
- R2.2 SE uma variável obrigatória faltar ou for inválida, ENTÃO o sistema DEVE recusar iniciar com mensagem que nomeia a variável.
- R2.3 ENQUANTO `APP_ENV=prod`, o sistema DEVE recusar iniciar com segredos de exemplo, `DEBUG` ligado ou conexão ao banco sem TLS.

### R3. Erros padronizados
- R3.1 O sistema DEVE responder todo erro no formato `application/problem+json` (RFC 9457) com `type`, `title`, `status`, `detail` e `request_id`.
- R3.2 QUANDO a validação de entrada falhar, o sistema DEVE responder 422 com a lista `errors[]` contendo `campo` e `mensagem` em português.
- R3.3 SE ocorrer erro inesperado, ENTÃO o sistema DEVE responder 500 sem expor stack trace ou detalhes internos.

### R4. Observabilidade
- R4.1 O sistema DEVE registrar cada requisição em log JSON com `request_id`, método, rota, status e duração.
- R4.2 O sistema DEVE aceitar `X-Request-ID` de entrada ou gerar um, e devolvê-lo na resposta.
- R4.3 O sistema NÃO DEVE registrar em log senhas, tokens, cookies ou segredos (filtro de chaves sensíveis).

### R5. Auditoria base
- R5.1 O sistema DEVE oferecer um serviço interno `audit.registrar(acao, entidade, mudancas, ator)` que grava em `audit_log` na mesma transação do caso de uso.
- R5.2 O sistema DEVE impedir UPDATE e DELETE em `audit_log` no nível do banco.
- R5.3 O sistema DEVE encadear cada registro ao anterior por hash SHA-256.

### R6. Segurança transversal
- R6.1 O sistema DEVE enviar cabeçalhos `Strict-Transport-Security`, `X-Content-Type-Options`, `Referrer-Policy` e `Cache-Control: no-store` nas rotas autenticadas.
- R6.2 O sistema DEVE aceitar CORS apenas das origens configuradas.
- R6.3 O sistema DEVE expor a documentação OpenAPI apenas em `dev` e `test`.

### R7. Esteira de qualidade
- R7.1 QUANDO um PR é aberto, o CI DEVE rodar lint, formatação, tipos, regras de arquitetura, testes, SAST, auditoria de dependências e verificação do contrato OpenAPI.
- R7.2 SE qualquer etapa falhar, ENTÃO o merge DEVE ficar bloqueado.

## Perguntas em aberto
- Qual integrante é o dono humano desta spec?
