# 004 · Diretório LDAP e OIDC · Requisitos

- Status: Rascunho
- Rastreia: RS-01, RS-02, RS-03, RS-05, RS-08, requisito obrigatório "consumo de credenciais via LDAP e OIDC para popular as tabelas locais dos usuários e grupos"

## Contexto
A Secretaria (como a maioria dos órgãos públicos) já mantém identidades em diretório corporativo. A API deve consumir essas identidades por LDAP e por OIDC, espelhá-las em `users`, `groups` e `user_groups`, e transformar grupos em papéis pelo mapeamento da spec 003.

## Fora do escopo
- Escrever no diretório (a API só lê).
- SCIM.
- Sincronização em tempo real (usamos job sob demanda e agendado).

## Histórias e critérios

### R1. Sincronização LDAP
Como Admin TI, quero importar usuários e grupos do diretório para não cadastrar ninguém à mão.

- R1.1 QUANDO o Admin TI dispara `POST /admin/diretorio/sincronizar`, o sistema DEVE responder 202 com o id da execução e processar em segundo plano.
- R1.2 O sistema DEVE conectar ao LDAP somente por LDAPS ou StartTLS, validando o certificado do servidor.
- R1.3 O sistema DEVE autenticar no LDAP com uma conta de serviço somente leitura configurada por variável de ambiente.
- R1.4 O sistema DEVE buscar usuários e grupos com paginação (RFC 2696) e apenas os atributos configurados.
- R1.5 QUANDO um usuário do diretório não existe localmente, o sistema DEVE criá-lo com `source = ldap` e `external_id` = DN (ou `entryUUID`, se disponível).
- R1.6 QUANDO um usuário já existe, o sistema DEVE atualizar nome, e-mail e status, e registrar `synced_at`.
- R1.7 QUANDO um usuário sincronizado anteriormente não aparece mais na busca, o sistema DEVE desativá-lo, nunca apagá-lo.
- R1.8 O sistema DEVE espelhar grupos e associações (`member`/`memberOf`) e recalcular as atribuições derivadas de grupos mapeados.
- R1.9 O sistema DEVE registrar a execução em `directory_sync_runs` com contagens e erros, e auditar `diretorio.sincronizado`.
- R1.10 SE o LDAP estiver indisponível, ENTÃO o sistema DEVE marcar a execução como `falhou` sem alterar nenhum dado local.
- R1.11 ENQUANTO uma sincronização estiver em andamento, o sistema DEVE recusar outra com 409.
- R1.12 ONDE `LDAP_SYNC_CRON` estiver configurado, o sistema DEVE executar a sincronização no horário definido.

### R2. Login por LDAP
- R2.1 QUANDO um usuário informa credenciais com `provider = ldap`, o sistema DEVE localizar o DN pela conta de serviço e validar a senha por *bind* com esse DN.
- R2.2 O sistema DEVE escapar todo valor usado em filtro LDAP.
- R2.3 QUANDO o bind for bem-sucedido, o sistema DEVE atualizar o usuário e seus grupos localmente e seguir para o 2FA da spec 002.
- R2.4 SE a senha estiver vazia, ENTÃO o sistema DEVE recusar antes de tentar o bind (evita bind anônimo aceito por engano).

### R3. Login por OIDC
- R3.1 QUANDO o usuário acessa `GET /auth/oidc/login`, o sistema DEVE redirecioná-lo ao provedor usando Authorization Code com PKCE (S256), `state` e `nonce`.
- R3.2 QUANDO o provedor chama o callback, o sistema DEVE validar `state`, trocar o código por tokens e validar assinatura, `iss`, `aud`, `exp` e `nonce` do `id_token`.
- R3.3 QUANDO o `id_token` é válido, o sistema DEVE criar ou atualizar o usuário (`source = oidc`, `external_id = sub`) e espelhar os grupos da claim configurada (padrão `groups`).
- R3.4 QUANDO o usuário é provisionado, o sistema DEVE emitir os tokens próprios da API (spec 002) e redirecionar ao front-end sem expor tokens na URL.
- R3.5 SE qualquer validação falhar, ENTÃO o sistema DEVE recusar o login, auditar `auth.oidc_failed` e redirecionar ao front-end com código de erro genérico.
- R3.6 ONDE `OIDC_REQUIRED_ACR` estiver configurado, o sistema DEVE recusar logins cujo `acr` não atenda ao mínimo (ex.: exigir MFA no provedor).

### R4. Consistência entre origens
- R4.1 O sistema NÃO DEVE permitir login por senha local para usuários com `source` diferente de `local`.
- R4.2 SE dois provedores apresentarem o mesmo e-mail, ENTÃO o sistema NÃO DEVE unir as contas automaticamente; DEVE registrar conflito na execução e auditar.

## Perguntas em aberto
- A Secretaria usa Active Directory ou OpenLDAP? (o design suporta ambos via configuração de atributos)
- Qual atributo do diretório indica distrito ou unidade, se houver? (útil para escopo automático)
