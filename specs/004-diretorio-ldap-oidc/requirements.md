# 004 · Diretório LDAP e OIDC · Requisitos

- Status: Aprovado (G1: Rafael, rafareloM, dono, em 24/11/2026, com as recomendações das perguntas de 24/11/2026 aceitas; registro do agente por autorização expressa na sessão de trabalho)
- Rastreia: RS-01, RS-02, RS-03, RS-05, RS-08, requisito obrigatório "consumo de credenciais via LDAP e OIDC para popular as tabelas locais dos usuários e grupos"
- Dono humano: Vinicius (ViniciusVbm) e Rafael (rafareloM), como responsáveis pelo projeto: a spec não tinha dono registrado (`steering/sdd-workflow.md` § Dono da spec). Linha registrada na revisão de 09/11/2026; Rafael acrescentado em 24/11/2026.

## Contexto
A Secretaria (como a maioria dos órgãos públicos) já mantém identidades em diretório corporativo. A API deve consumir essas identidades por LDAP e por OIDC, espelhá-las em `users`, `groups` e `user_groups`, e transformar grupos em papéis pelo mapeamento da spec 003.

## Fora do escopo
- Escrever no diretório (a API só lê).
- SCIM.
- Sincronização em tempo real (usamos job sob demanda e agendado).
- Unir contas da mesma pessoa vindas de origens diferentes (proposto em 24/11/2026; ver R4.3 e Perguntas em aberto).

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
- R1.13 SE o certificado do servidor LDAP não for emitido pela CA configurada ou não corresponder ao nome do servidor, ENTÃO o sistema DEVE recusar a conexão antes de enviar qualquer credencial e tratar a falha como em R1.10. (novo, 24/11/2026)
- R1.14 QUANDO o Admin TI lista os grupos espelhados, o sistema DEVE devolver de cada um o id, a origem, o nome e o número de membros ativos, para que o grupo possa ser mapeado a um papel (spec 003, R3.1). (novo, 24/11/2026)

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
- R3.7 SE o `state` recebido no callback já tiver sido usado ou estiver vencido, ENTÃO o sistema DEVE recusar o login como em R3.5. (novo, 24/11/2026)
- R3.8 O sistema DEVE usar o endereço de retorno registrado no provedor (`redirect_uri`) e o destino no front-end definidos em configuração, nunca obtidos da requisição. (novo, 24/11/2026)
- R3.9 ONDE o OIDC estiver configurado, a tela de login do front-end DEVE oferecer a entrada pelo provedor; no retorno, DEVE abrir a sessão pela renovação da spec 002, sem receber token pela URL (R3.4), ou mostrar a mensagem do código de erro genérico (R3.5). (novo, 24/11/2026; toca o front-end da spec 012, ver Perguntas em aberto)

### R4. Consistência entre origens
- R4.1 O sistema NÃO DEVE permitir login por senha local para usuários com `source` diferente de `local`.
- R4.2 SE dois provedores apresentarem o mesmo e-mail, ENTÃO o sistema NÃO DEVE unir as contas automaticamente; DEVE registrar conflito na execução e auditar.
- R4.3 SE o login por LDAP ou por OIDC precisar criar uma conta com e-mail já usado por conta de outra origem, ENTÃO o sistema DEVE recusar o login com erro genérico, sem criar nem alterar conta, e auditar o conflito. (novo, 24/11/2026)
- R4.4 SE a conta local de um usuário de diretório estiver inativa, ENTÃO o sistema DEVE recusar o login por LDAP ou por OIDC; o login NÃO DEVE reativar a conta. (novo, 24/11/2026)

### R5. Ambiente de demonstração
Como integrante do grupo, quero demonstrar a sincronização e os dois logins federados no ambiente local, sem depender da infraestrutura da Secretaria.

Novo em 24/11/2026. A spec 001 (R1.1) deixou o LDAP e o provedor OIDC do compose para esta spec, mas nenhum critério os pedia: a T8 rastreava só a R1.2.

- R5.1 QUANDO alguém sobe o ambiente local seguindo o README, o sistema DEVE subir também um servidor LDAP de laboratório, acessível só por LDAPS com certificado de uma CA de desenvolvimento, com usuários e grupos de exemplo que cubram os papéis da spec 003.
- R5.2 QUANDO alguém sobe o ambiente local seguindo o README, o sistema DEVE subir também um provedor OIDC de laboratório, com um cliente confidencial da API (PKCE S256), usuários e grupos de exemplo e a claim de grupos da R3.3.
- R5.3 O ambiente local DEVE permitir demonstrar de ponta a ponta: a sincronização criando, atualizando e desativando usuários e grupos (R1.5–R1.8); a recusa de certificado LDAP não confiável (R1.13); o login por LDAP com 2FA (R2); e o login OIDC até a emissão dos tokens da API (R3.1–R3.4).
- R5.4 SE a API iniciar com `APP_ENV=prod` usando a senha da conta de serviço LDAP ou o segredo do cliente OIDC do laboratório, ENTÃO o sistema DEVE recusar iniciar, como faz com os demais segredos de exemplo (spec 001, R2.3).

## Perguntas em aberto
- A Secretaria usa Active Directory ou OpenLDAP? (o design suporta ambos via configuração de atributos)
- Qual atributo do diretório indica distrito ou unidade, se houver? (útil para escopo automático)
- (revisão de 09/11/2026, agente; aguarda o dono) O ADR-0003 (identidade federada com tokens próprios), base desta spec, está `Proposto`. Convém aceitá-lo junto com a aprovação dos requisitos.
- (revisão de 24/11/2026, agente; aguarda o dono) Federação no provedor de laboratório. O design põe no Keycloak uma federação LDAP que aponta para o mesmo `slapd` da sincronização. Assim, a mesma pessoa chega como `source = ldap` (pela sincronização) e como `source = oidc` (pelo login), e `users.email` é único: pela R4.3, o login OIDC de todo usuário já sincronizado seria recusado. Recomendação: no laboratório, o realm tem usuários e grupos próprios, sem federação (R5.2), e unir contas fica fora do escopo. Se a Secretaria usar o mesmo diretório nas duas origens, o vínculo pelo identificador do diretório (uma claim com o `entryUUID`) entra numa emenda.
- (revisão de 24/11/2026, agente; aguarda o dono) A R3.9 muda a tela de login, que é da spec 012 (`Aprovado`; o dono também é o Vinicius), e a 012 não prevê entrada OIDC. Recomendação: a tarefa fica nesta spec, com nota de referência no design da 012, como a 013 fez com a 001 e a 011. A outra via é uma emenda funcional da 012, com G1 próprio. O retorno já se encaixa na abertura atual do front-end, que chama a renovação antes de mostrar o login (design da 012, passo "Abertura").
- (004/T1, 25/11/2026, agente; aguarda o dono) Mapeamento para grupo inexistente. Com a FK `group_role_mappings.group_id` → `groups.id` da `0004_diretorio`, um `POST /admin/mapeamentos-grupo` com `grupo_id` que não está em `groups` viola a FK no banco, e a resposta hoje não é definida (sai como erro interno). Nem a 003 (R3.1, padrão adotado da T8) nem esta spec dizem o que responder. Recomendação: 422 em `grupo_id` ("grupo não encontrado"), conferido pela aplicação antes de gravar, como as regras de escopo; a outra via é 404. Decidir antes da T4 (listagem de grupos, que dá o `grupo_id` ao Admin TI). Até lá, os testes da 003/T8 criam o grupo antes de mapear.
- (004/T3, 25/11/2026, agente; aguarda o dono) Entrada inválida no diretório. Um usuário com e-mail fora do formato, `username` acima de 100 caracteres ou nome acima de 200 não cabe em `users`, e nenhum critério diz o que fazer com ele. Hoje a validação do `User` recusa, a transação B é desfeita e a execução fica `falhou` ("Falha na sincronização"), como manda a R1.10 para qualquer erro: uma entrada ruim impede a sincronização de todas. Recomendação: tratar a entrada como o conflito da R4.2 (pular, registrar na execução com um `tipo` novo, `invalido`, e seguir), o que pede emenda na R4.2 ou um critério novo.
- (revisão de código da frente A, 26/11/2026, agente; aguarda o dono) Desativação em massa. Pela R1.7, uma busca que volte vazia ou cortada (um `LDAP_USER_FILTER` ou `LDAP_USER_BASE` errado) desativa todas as contas LDAP e remove as atribuições derivadas delas numa execução só. Recomendação: recusar a aplicação (execução `falhou`) quando o retrato vier sem usuários e houver contas LDAP ativas, e, se o dono quiser, também acima de uma fração configurável de desativações. Pede um critério novo junto à R1.7.
- (revisão de código da frente A, 26/11/2026, agente; aguarda o dono) Auditoria da atualização no login LDAP. Quando o login atualiza nome ou e-mail de uma conta existente (R2.3), nenhum evento é gravado: o design lista só `usuario.provisionado` para a criação, e a sincronização registra a mudança no agregado `diretorio.sincronizado`. A regra 5 do `AGENTS.md` pede auditoria de toda alteração de dado de negócio. Recomendação: um evento `usuario.atualizado` (origem `ldap`, só os nomes dos campos mudados, sem os valores), o que pede ajuste no design § Segurança.

## Decisões do G1 (Rafael, 24/11/2026)
- Realm do Keycloak de laboratório com usuários e grupos próprios, sem federação com o `slapd`; unir contas de origens diferentes fica fora do escopo.
- A entrada OIDC no front-end (R3.9) é tarefa desta spec, com nota de referência no design da 012.
- O ADR-0003 passa a `Aceito`.
- Continuam abertas, sem bloquear o design: AD ou OpenLDAP na Secretaria (o design suporta os dois por configuração) e o atributo de distrito ou unidade.

## Revisão de 24/11/2026: checklist da disciplina
- Quem e por quê: agente, a pedido do Rafael; G1 aprovado pelo Rafael no mesmo dia (seção acima). Comparação dos itens de LDAP e OIDC do checklist de acompanhamento acadêmico (`docs/requisitos-iam.docx`, § 3, fora do Git nesta data) com os critérios desta spec.
- O checklist marca como concluídos itens que ainda não têm código. A situação real está em `docs/REQUISITOS_EVIDENCIAS.md` (linhas de grupos e de LDAP/OIDC): nada desta spec foi implementado. O item "19 testes automatizados" não é requisito e fica de fora.
- Status sem mudança: o agente não aprova. Design e tarefas não foram reescritos antes do G1 (`/spec-design`, passo 1); os ajustes que os critérios novos pedem estão no fim de cada arquivo.

| Item do checklist | Critérios | Situação na spec |
|---|---|---|
| Módulo de identidade em `src/modules/identity/` | design § Portas e adaptadores | coberto |
| Componentes de comunicação LDAP | R1.2–R1.4, R2.1 | coberto |
| Consultas LDAP com paginação | R1.4 | coberto |
| Validação de certificados LDAPS | R1.2, **R1.13** | faltava o caso negativo testável |
| Validação de tokens OIDC via JWKS | R3.2 | coberto |
| Validação de `iss`, `aud`, `exp`, `nonce` e `acr` | R3.2, R3.6 | coberto |
| Sincronização de usuários e grupos | R1.5–R1.9, **R1.14** | sem a lista de grupos, o Admin TI não tem o `grupo_id` que o mapeamento da 003 pede |
| Testes automatizados com mocks | design § Estratégia de testes | coberto |
| Validação com um servidor LDAP real | **R5.1**, **R5.3** | faltava: o compose não tem LDAP e nenhum critério o pedia |
| Fluxo completo de autenticação OIDC | R3.1–R3.6, **R3.9** | faltava a entrada pelo front-end |
| Callback OIDC com Authorization Code + PKCE | R3.1, R3.2, **R3.7**, **R3.8** | faltavam o `state` de uso único e o retorno fixo (sem redirecionamento aberto) |
| Login federado com emissão dos tokens da API | R3.4, **R4.3**, **R4.4** | faltava o que fazer com e-mail já usado (`users.email` é único) e com conta inativa |
| Demonstração da sincronização real | R1.5–R1.8, R1.14, **R5.3** | faltava |
| Fora do checklist: "consumo de credenciais via LDAP", do texto da disciplina | R2 | coberto; o login por bind LDAP fica, porque o texto da disciplina o pede |
