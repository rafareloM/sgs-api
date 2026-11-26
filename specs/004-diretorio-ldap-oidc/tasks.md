# 004 · Diretório LDAP e OIDC · Tarefas

- Status: **Aprovado (G3: Rafael (rafareloM), dono, em 24/11/2026)**. Registro do agente por autorização expressa dada na sessão de trabalho. Pela tabela de `steering/sdd-workflow.md`, o G3 é só do dono. Execução em três frentes, com guias em `docs/implementacao/`.
- Requisitos e design: `Aprovado` (G1 e G2 do Rafael em 24/11/2026).
- Depende de: 002 (login, 2FA, refresh), 003/T8 (mapeamento e recálculo, fora da `main`; § Frentes), 012 (tela de login, na T10).
- Histórico: lista de 03/10/2026 (T1 a T9); notas de 09/11/2026 e 24/11/2026; reescrita por agente em 24/11/2026 com `/spec-tarefas`, depois do G2. A reescrita aplica as notas, cobre os critérios novos e divide o trabalho das specs 004 e 005 em três frentes simultâneas (Decisões do G2). As tarefas antigas mantêm o número quando o conteúdo é o mesmo; as novas vêm depois da T9.

Cada tarefa é pequena (até ~300 linhas de diff), testável e cita os requisitos que cobre. Só se marca `[x]` quando o teste citado passa e o `make check` está verde. Arquivos de teste citados aqui ainda não existem e nascem na tarefa, menos `tests/unit/core/test_config.py` e `tests/architecture/test_rotas_protegidas.py`, que só ganham testes.

## Frentes de trabalho (specs 004 e 005)
O mesmo quadro está em `specs/005-exportacao-relatorios-s3/tasks.md`. Cada frente roda num *worktree* próprio, a partir do ramo de integração `feat/004-005`, e segue a ordem da coluna. As estimativas são em horas de trabalho focado.

| Frente | Ordem | Estimativa |
|---|---|---|
| Base (antes de dividir) | 004/T0 = 005/T0 (uma tarefa só, um commit) | 2 h |
| **A · Diretório LDAP** | 003/T8 (porte) → 004/T1 → T2 → T11 → T12 → T3 → T5 → T4 → T9 → 005/T7 | 35 a 50 h |
| **B · OIDC e laboratório** | 004/T8 → T13 → 005/T9 → 004/T6 → T10 → T7 → T14 | 30 a 48 h |
| **C · Relatórios** | 005/T10 → T12 → T1 → T2 → T11 → T3 → T4 → T5 → T6 → T8 | 35 a 52 h |

**Pontos de encontro.** A tarefa da esquerda espera a da direita estar integrada em `feat/004-005`.

| Quem espera | Precisa de | Folga prevista |
|---|---|---|
| B · 004/T7 (callback) | A · 003/T8 e 004/T1 | grande: A faz as duas primeiro |
| C · 005/T5 (geração) | B · 005/T9 (assinatura) | média: B faz a 005/T9 em terceiro |
| C · 005/T8 (SeaweedFS no compose) | B · 004/T8 (`servicos-certs`, redes, Caddy) | grande: é a primeira de B |
| B · 004/T14 (ponta a ponta) | A · 004/T4, T5 e T11 | pequena: se A atrasar, B adianta o roteiro da T14 |

**Regras de integração:**
- **Ramos.** O `feat/004-005` sai da `main` depois que o PR das specs (`docs/004-005-revisao-checklist`) entrar. A T0 é feita nele antes de abrir as frentes.
- **Quando integrar.** Cada tarefa pronta é rebaseada e integrada no `feat/004-005` antes de outra frente usá-la.
- **Testes.** Os de integração usam Testcontainers e precisam de Docker: rodam num terminal do host, não no VS Code em Flatpak.
- **Migrações.** A 004/T1 cria `0004_diretorio` e a 005/T1 cria `0005_relatorios`, as duas com `down_revision` na cabeça do momento. Quem integrar por último aponta o seu `down_revision` para a outra. Depois de cada integração, `alembic heads` mostra uma cabeça só.
- **Arquivos compartilhados:**
  - `pyproject.toml` e `uv.lock`: só a T0;
  - `src/core/config.py`: cada área acrescenta o seu bloco de campos e o seu método `_<área>_problems()`, e o conflito fica só na lista de chamadas;
  - `src/main.py`: uma linha por roteiro e por fábrica;
  - `docker/compose.yml`, `docker/caddy/Caddyfile`, `.env.example` e `README.md`: só a frente B até a 004/T13 estar integrada, depois a 005/T8;
  - OIDC em arquivo novo (`identity/api/oidc.py`); a 004/T5 e a 004/T7 mexem em trechos diferentes de `auth.py` e `login.py`.
- **PR.** Um PR por spec para a `main`, a partir do `feat/004-005`, quando todas as tarefas da spec estiverem `[x]`.

## Dependências
| Tarefa | Frente | Depende de | Por quê |
|---|---|---|---|
| T0 | base | — | dependências e erro 503 usados pelas duas specs |
| 003/T8 | A | — | mapeamento e recálculo (contrato `recalcular_derivadas_do_usuario`) |
| T1 | A | T0 | tabelas e repositórios |
| T2 | A | T0 | `ldap3` e configuração |
| T11 | A | T2 | a conferência de TLS é do adaptador |
| T12 | A | — | função pura do domínio |
| T3 | A | T1, T12, 003/T8 | aplica o plano no banco e recalcula as derivadas |
| T5 | A | T1, T2, 003/T8 | login grava conta e grupos e recalcula |
| T4 | A | T3 | rotas sobre o caso de uso; troca o `SemMembrosDeGrupo` da 003/T8 |
| T9 | A | T3 | o agendador chama o caso de uso |
| T8 | B | — | compose; não usa código novo |
| T13 | B | T8 | o `slapd` usa o `servicos-certs` e as redes da T8 |
| T6 | B | T0 | Authlib, httpx e PyJWT |
| T10 | B | — | front com a API simulada |
| T7 | B | T1, T6, 003/T8 | tabelas, validação e recálculo |
| T14 | B | T4, T5, T7, T10, T11, T13 | ponta a ponta de tudo |

## Tarefas
- [x] T0. Base comum das specs 004 e 005. É a mesma tarefa que a 005/T0, num commit `(004/T0, 005/T0)`.
  - Concluída em 24/11/2026 (`make check` verde). Prova: `tests/unit/core/test_errors.py::test_service_unavailable_responde_503`
  - Frente: base
  - Faz:
    - entram `ldap3` 2.9.1, `Authlib` 1.9.x (ADR-0007, emenda 3), `httpx` 0.28.x (passa do grupo `dev` para a execução; ADR-0007, emenda 2), `boto3` 1.43.x e `openpyxl` 3.1.x;
    - `moto` 5.x entra no grupo `dev`;
    - sobreposições do mypy para as bibliotecas sem tipos;
    - `ServiceUnavailable(AppError)` com status 503 em `src/core/errors.py`.
  - Requisitos: — (infraestrutura das tarefas seguintes)
  - Pronto quando: `uv.lock` travado, `tests/unit/core/test_errors.py::test_service_unavailable_responde_503` passa e o `make check` está verde
- [x] T1. Migração `0004_diretorio` e repositórios do diretório
  - Concluída em 25/11/2026 (`make check` verde). Prova: `tests/integration/identity/test_directory_tables.py::test_uma_execucao_em_andamento_por_vez`, `::test_state_do_oidc_e_consumido_uma_vez`, `::test_mapeamento_exige_grupo_existente` e `::test_migracao_para_se_houver_mapeamento_orfao` (arquivo inteiro passa)
  - Frente: A
  - Faz:
    - `groups`, `user_groups`, `directory_sync_runs` com o índice único parcial e `oidc_login_requests` (design § Modelo de dados);
    - FK de `group_role_mappings.group_id`, com a conferência de órfãos;
    - `SqlDirectoryRepository` (*upserts* por `ON CONFLICT`, troca de associações, execuções) e `SqlOidcLoginRequests` (consumo atômico do `state`);
    - `modelo-dados.md` § 1.
  - Bloqueada por: T0
  - Requisitos: R1.9, R1.11, R1.14, R3.7
  - Pronto quando: `tests/integration/identity/test_directory_tables.py` passa
- [x] T2. Configuração LDAP e adaptador `ldap3`
  - Concluída em 25/11/2026 (`make check` verde). Prova: `tests/unit/identity/test_ldap3_adapter.py::test_snapshot_pagina_e_pede_so_os_atributos_configurados`
  - Frente: A
  - Faz:
    - campos `LDAP_*` em `Settings`, com as regras de esquema, CA e obrigatórias (`_ldap_problems`) e a recusa da senha de exemplo em `prod`;
    - `DirectoryPort`, `DirectoryUser`, `DirectoryGroup`, `DirectoryUnavailable` no domínio;
    - `ldap3_directory.py`: busca paginada, só os atributos configurados, `find_user`, `verify_password`, `groups_of`, `escape_filter_chars`, recusa de senha vazia e chamadas em *thread*.
  - Bloqueada por: T0
  - Requisitos: R1.2, R1.3, R1.4, R2.1, R2.2, R2.4, R5.4
  - Pronto quando: `tests/unit/identity/test_ldap3_adapter.py` e os testes LDAP de `tests/unit/core/test_config.py` passam
- [x] T11. Conferência do TLS do LDAP e `sgs-admin diretorio testar`
  - Concluída em 25/11/2026 (`make check` verde). Prova: `tests/integration/identity/test_ldap_tls.py::test_tls_do_ldap_e_conferido_antes_de_qualquer_credencial`
  - Frente: A
  - Faz:
    - servidor TLS local em *thread* no teste;
    - CA errada e nome errado recusados antes de qualquer byte LDAP;
    - se o *backport* do `ldap3` falhar, o adaptador passa a usar um `ssl.SSLContext` com `check_hostname` (design § Riscos);
    - subcomando `sgs-admin diretorio testar [--url] [--ca]`, sem gravar nada.
  - Bloqueada por: T2
  - Requisitos: R1.2, R1.13
  - Pronto quando: `tests/integration/identity/test_ldap_tls.py` passa
- [x] T12. Plano da sincronização (domínio puro)
  - Concluída em 25/11/2026 (`make check` verde). Prova: `tests/unit/identity/test_plano_sincronizacao.py::test_um_conflito_nao_para_os_demais`
  - Frente: A
  - Faz: `planejar(retrato, locais)` cobre criar, atualizar, reativar e desativar contas; grupos e associações; conflitos de e-mail e de `username`.
  - Bloqueada por: —
  - Requisitos: R1.5, R1.6, R1.7, R1.8, R4.2
  - Pronto quando: `tests/unit/identity/test_plano_sincronizacao.py` passa
- [x] T3. Caso de uso da sincronização
  - Frente: A
  - Faz:
    - leitura fora de transação e aplicação numa transação só;
    - `recalcular_derivadas_do_usuario` para quem mudou de grupo e para os desativados;
    - `diretorio.sincronizado` e `diretorio.conflito`;
    - falha sem tocar em dado local, com mensagem genérica e transação própria para o `falhou`;
    - execuções interrompidas marcadas na subida.
  - Bloqueada por: T1, T12, 003/T8
  - Requisitos: R1.5, R1.6, R1.7, R1.8, R1.9, R1.10, R4.2
  - Pronto quando: `tests/integration/identity/test_ldap_sync.py` passa
  - Concluída em 25/11/2026 (`make check` verde). Prova: `tests/integration/identity/test_ldap_sync.py` (arquivo inteiro passa), em especial `::test_diretorio_fora_marca_falhou_sem_tocar_em_dado_local` e `::test_mudanca_de_grupo_recalcula_as_derivadas_da_003`. Notas: o conflito com outro usuário do mesmo retrato grava `usuario_existente_id = null`; entrada inválida no diretório falha a execução inteira (pergunta em aberto em `requirements.md`, 004/T3).
- [x] T5. Login por LDAP
  - Frente: A
  - Faz:
    - `provider` em `LoginIn`;
    - `entrar_por_ldap`: bloqueio antes do *bind*, provisionamento, grupos, recálculo, conflito, conta inativa sem reativar;
    - `amr` pela origem em `_concluir_mfa`;
    - 503 com o diretório fora;
    - `make openapi`.
  - Bloqueada por: T1, T2, 003/T8
  - Requisitos: R2.1, R2.2, R2.3, R2.4, R4.1, R4.3, R4.4
  - Pronto quando: `tests/integration/identity/test_ldap_login.py` passa
  - Concluída em 25/11/2026 (`make check` verde). Prova: `tests/integration/identity/test_ldap_login.py` (arquivo inteiro passa), em especial `::test_cinco_falhas_bloqueiam_e_o_bloqueio_vem_antes_do_bind`, `::test_conflito_de_email_recusa_sem_criar_conta` e `::test_2fa_do_usuario_ldap_abre_sessao_com_amr_ldap_otp`. Notas: sem LDAP_URL, `provider = "ldap"` responde 503, como a rota de sincronização; no login de conta existente, um e-mail novo que já é de outra conta mantém o antigo, como na sincronização; com o 2FA desligado em dev, o `amr` é `ldap`; o fim de `entrar` virou `desafiar_ou_abrir_sessao`, pública, para o login LDAP reusar.
- [x] T4. Rotas da sincronização, das execuções e dos grupos
  - Frente: A
  - Faz:
    - `POST /admin/diretorio/sincronizar` (202, 409, 503);
    - `GET /execucoes` e `GET /execucoes/{id}`;
    - `GET /admin/diretorio/grupos` com `papel:assign` e membros ativos;
    - troca o `SemMembrosDeGrupo` da 003/T8 pela leitura de `user_groups`;
    - `make openapi`.
  - Bloqueada por: T3
  - Requisitos: R1.1, R1.9, R1.11, R1.14
  - Pronto quando: `tests/integration/identity/test_sync_routes.py` passa, com 401, 403 e 422
  - Concluída em 26/11/2026 (`make check` verde). Prova: `tests/integration/identity/test_sync_routes.py` (arquivo inteiro passa, com 401, 403 e 422), em especial `::test_disparo_responde_202_e_a_execucao_fica_consultavel`, `::test_segunda_execucao_em_andamento_responde_409` e `::test_mapear_grupo_atribui_o_papel_aos_membros_ativos_de_user_groups`; `tests/integration/audit/test_cobertura_rotas.py` cobre a rota nova. Notas: o `SemMembrosDeGrupo` virou `SqlMembrosDeGrupo` (`access/infrastructure/repository.py`); a execução é gravada numa transação própria, confirmada antes do 202, e a rota usa `SessaoDeNegocio` só para o 409 virar `operacao.falhou`; a resposta de listagem segue `PaginaOut` (`itens`, `total`, `pagina`, `tamanho`). A pergunta da 004/T1 sobre `grupo_id` inexistente no mapeamento continua aberta (sai como erro interno).
- [x] T9. Agendamento da sincronização
  - Frente: A
  - Faz:
    - analisador do subconjunto de cron no domínio (fuso de Recife);
    - tarefa `asyncio` no lifespan, que pula se já houver execução e é cancelada no desligamento;
    - ator `sistema`, origem `agendador`.
  - Bloqueada por: T3
  - Requisitos: R1.12
  - Pronto quando: `tests/unit/identity/test_cron.py` e `tests/integration/identity/test_sync_schedule.py` passam
  - Concluída em 26/11/2026 (`make check` verde). Prova: `tests/unit/identity/test_cron.py` e `tests/integration/identity/test_sync_schedule.py` (os dois arquivos inteiros passam), em especial `::test_laco_espera_ate_cada_horario_no_fuso_de_recife`, `::test_agendada_pula_se_ja_houver_execucao_em_andamento` e `::test_lifespan_inicia_o_agendador_e_o_cancela_no_desligamento`. Notas: o domínio não importa `src.core`, então `LDAP_SYNC_CRON` é conferida pela raiz de composição (`create_app`), que recusa a subida com `SettingsError`, e não por `Settings`; como as demais variáveis LDAP, só vale com `LDAP_URL`; no `.env.example` ela fica comentada, e o compose não muda.
- [x] T8. Laboratório: peças compartilhadas e Keycloak
  - Frente: B
  - Primeira hora: conferir que o `iss` é o mesmo pela descoberta pública (via Caddy) e pela interna. Se não for, parar e registrar a alternativa no design antes de seguir (design § Riscos).
  - Faz:
    - serviço `servicos-certs` (CA de laboratório; certificados `ldap`, `keycloak` e `s3`);
    - redes `integracoes` e `exposicao`;
    - Keycloak com tag fixa e `docker/keycloak/realm-sgs.json` (usuários e grupos próprios, cliente confidencial com PKCE S256, *mapper* `groups`, segredo `sgs-lab-exemplo-oidc`);
    - bloco `keycloak.localhost` no Caddy;
    - variáveis `SGS_PUBLIC_URL` e `SGS_PUBLIC_KEYCLOAK_URL`;
    - `OIDC_*` da API no compose;
    - `.env.example` e README.
  - Bloqueada por: —
  - Requisitos: R5.2
  - Pronto quando: `tests/e2e/test_lab_keycloak.py -m slow` passa, conferindo:
    - o mesmo `issuer` pelos dois caminhos;
    - PKCE S256 exigido;
    - a claim `groups` no `id_token` de um usuário de exemplo.
  - Concluída em 25/11/2026 (`make check` verde). Prova: `tests/e2e/test_lab_keycloak.py::test_issuer_e_o_mesmo_pela_descoberta_publica_e_pela_interna`, `::test_cliente_exige_pkce_s256_e_a_redirect_uri_exata` e `::test_id_token_traz_a_claim_groups` (`-m slow`). O `iss` é o mesmo nos dois caminhos.
  - Nota de execução (Rafael, 25/11/2026): Keycloak 26.8.2 em `start --import-realm`, e não em `start-dev` (design § Keycloak). O perfil dev abre HTTP na 8080 mesmo com `KC_HTTP_ENABLED=false`; `test_keycloak_so_atende_https_na_rede` confere. Fora da lista da frente, com autorização: `tests/architecture/test_proxy_confiavel.py` (redes e suíte novas).
- [x] T13. Laboratório: `slapd` só com LDAPS
  - Frente: B
  - Faz:
    - `docker/ldap/Dockerfile` (Debian e `slapd`);
    - `seed.ldif` com a conta de serviço só leitura, um usuário por papel, um a mais para desativar e grupos com papel e escopo no nome;
    - escuta só `ldaps:///` e `ldapi:///`;
    - *alias* `ldap-nome-errado`;
    - `LDAP_*` da API no compose, com a senha `sgs-lab-exemplo-bind`.
  - Bloqueada por: T8
  - Requisitos: R5.1
  - Pronto quando: `tests/e2e/test_lab_ldap.py -m slow` passa, conferindo:
    - busca da conta de serviço por LDAPS com a CA de laboratório;
    - sem porta LDAP em texto claro;
    - escrita recusada para a conta de serviço.
  - Concluída em 25/11/2026 (`make check` verde). Prova: `tests/e2e/test_lab_ldap.py::test_conta_de_servico_busca_por_ldaps_com_a_ca_de_laboratorio`, `::test_sem_porta_ldap_em_texto_claro` e `::test_conta_de_servico_nao_escreve_nem_le_senhas` (`-m slow`).
  - Nota de execução (Rafael, 25/11/2026): OpenLDAP 2.6.10 do Debian trixie, como uid 389. A carga inicial fica no volume `ldap-data`, para os `entryUUID` acompanharem o `db-data` entre as subidas. O *healthcheck* espera a 636, que só abre depois da carga. Sem o *overlay* `refint` (o design não o pede): apagar uma pessoa no roteiro deixa o DN dela no `member` do grupo. Fora da lista da frente, com autorização: `tests/architecture/test_proxy_confiavel.py` (serviço `ldap` e suíte nova).
- [x] T6. Configuração OIDC e validação do `id_token`
  - Concluída em 25/11/2026 (`make check` verde). Prova: `tests/unit/identity/test_oidc_validacao.py`, `tests/unit/core/test_config.py::{test_oidc_fica_desligado_sem_oidc_issuer, test_oidc_completo_e_aceito_com_descoberta_padrao, test_oidc_usa_a_url_de_descoberta_configurada, test_oidc_incompleto_recusa_a_subida_e_nomeia_a_variavel, test_oidc_recusa_endereco_sem_https_ou_fora_do_formato, test_oidc_recusa_frontend_url_fora_de_cors_origins, test_prod_recusa_segredo_oidc_de_exemplo, test_prod_aceita_segredo_oidc_de_verdade, test_segredo_oidc_de_exemplo_vale_fora_de_prod}`
  - Frente: B
  - Faz:
    - campos `OIDC_*` e `FRONTEND_URL` em `Settings`: `https://`, caminho do callback, origem do front em `CORS_ORIGINS`, segredo de exemplo recusado em `prod`;
    - `OidcPort`, `OidcIdentity`, `OidcRejected` no domínio;
    - `authlib_oidc.py`: descoberta com o `issuer` conferido, URL de autorização com S256 e `acr_values`, troca do código, validação pelo PyJWT, JWKS com recarga única por `kid` desconhecido.
  - Bloqueada por: T0
  - Requisitos: R3.2, R3.6, R3.8, R5.4
  - Pronto quando: `tests/unit/identity/test_oidc_validacao.py` e os testes OIDC de `tests/unit/core/test_config.py` passam
  - Nota de execução (Rafael, 25/11/2026), para a T7:
    - `authorization_url` levanta `ServiceUnavailable` (503) com o provedor fora do ar ou com descoberta de outro emissor. A T7 decide se `GET /auth/oidc/login` responde 503 ou redireciona para `FRONTEND_URL?login_erro=oidc`: a tabela de rotas do design lista só 404 e 429.
    - Motivos de recusa além dos do design: `iat` ausente ou no futuro dá `exp`; `sub` ausente ou longo demais dá `claims`. Claim de grupos ausente vale como nenhum grupo. Sem `name`, o nome exibido é o `username`.
    - `azp`, quando presente, tem de ser `OIDC_CLIENT_ID` mesmo com uma audiência só. É mais estrito que o design § Portas e adaptadores, como recomenda o OIDC Core § 3.1.3.7.
    - Ficam para a T7: o limite de 200 grupos (passo 4 do callback) e o cálculo do `code_challenge` no domínio (passo 1).
    - `OIDC_*` e `FRONTEND_URL` vazias valem como ausentes: `OIDC_ISSUER=` desliga o OIDC.
    - Decisões que a T7 também segue: design § Decisões de execução.
- [x] T10. Entrada OIDC no front-end
  - Concluída em 25/11/2026 (`make check` verde). Prova: `tests/e2e_front/test_login_oidc.py`
  - Frente: B
  - Faz:
    - `views/login.js` mostra o link "Entrar pelo provedor de identidade" só com `oidc = true` em `/auth/provedores`;
    - `main.js` trata `login_erro=oidc` e limpa a URL.
  - Bloqueada por: —
  - Requisitos: R3.9
  - Pronto quando: `tests/e2e_front/test_login_oidc.py` passa (Playwright, API simulada por `page.route`)
- [x] T7. Rotas OIDC: provedores, início e callback
  - Concluída em 26/11/2026 (`make check` verde). Prova: `tests/integration/identity/test_oidc_callback.py`, `tests/architecture/test_rotas_protegidas.py`
  - Frente: B
  - Faz:
    - `identity/api/oidc.py`: `GET /auth/provedores`, `GET /auth/oidc/login` com cookie de vínculo e limite por IP, e `GET /auth/oidc/callback`;
    - consumo do `state` em transação confirmada antes da troca;
    - provisionamento com conflito e conta inativa, grupos e recálculo;
    - sessão com `amr = oidc` e só o cookie de refresh;
    - 302 para o front, ou `login_erro=oidc` com `auth.oidc_failed`;
    - `PUBLICAS` com justificativa;
    - `make openapi`.
  - Bloqueada por: T1, T6, 003/T8
  - Requisitos: R3.1, R3.2, R3.3, R3.4, R3.5, R3.7, R3.8, R4.3, R4.4
  - Pronto quando: `tests/integration/identity/test_oidc_callback.py` e `tests/architecture/test_rotas_protegidas.py` passam
- [ ] T14. Demonstração ponta a ponta e roteiro
  - Frente: B
  - Faz:
    - testes `slow` contra o compose: sincronização que cria, altera e desativa; recusa pela CA do banco e por `ldap-nome-errado` com `sgs-admin diretorio testar`; login LDAP com cadastro do TOTP (`pyotp`); login OIDC pelo navegador até `/me`;
    - `docs/operacao/demo-diretorio.md`;
    - nota de referência no design da 012 (§ Abertura), sem mudar o texto normativo dela (design § Front-end).
  - Bloqueada por: T4, T5, T7, T10, T11, T13
  - Requisitos: R5.3, R1.13, R3.9
  - Pronto quando: `tests/e2e/test_sync_ldap.py -m slow` e `tests/e2e/test_login_ldap_oidc.py -m slow` passam

## Cobertura dos requisitos
| Requisito | Tarefas |
|---|---|
| R1.1 | T4 |
| R1.2 | T2, T11 |
| R1.3, R1.4 | T2 |
| R1.5–R1.8 | T12, T3 |
| R1.9 | T1, T3, T4 |
| R1.10 | T3 |
| R1.11 | T1, T4 |
| R1.12 | T9 |
| R1.13 | T11, T14 |
| R1.14 | T1, T4 |
| R2.1, R2.2, R2.4 | T2, T5 |
| R2.3 | T5 |
| R3.1 | T7 |
| R3.2 | T6, T7 |
| R3.3–R3.5 | T7 |
| R3.6 | T6 |
| R3.7 | T1, T7 |
| R3.8 | T6, T7 |
| R3.9 | T10, T14 |
| R4.1 | T5 |
| R4.2 | T12, T3 |
| R4.3, R4.4 | T5, T7 |
| R5.1 | T13 |
| R5.2 | T8 |
| R5.3 | T14 |
| R5.4 | T2, T6 |

Sem cobertura: nenhum.
