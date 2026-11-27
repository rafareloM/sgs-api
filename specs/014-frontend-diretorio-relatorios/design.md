# 014 · Front-end do diretório e dos relatórios · Design

- Status: **Aprovado (G2: Rafael (rafareloM), dono, em 26/11/2026)**. Registro do agente por autorização expressa dada na sessão de trabalho. Aprovação só do dono, pela exceção de `steering/sdd-workflow.md` § Exceção pontual: spec 014. **Limitação: o design não teve revisão de um segundo integrante.**
- Requisitos: requirements.md

## Visão geral
Duas telas novas no front da 012, só com rotas que já existem na `main` (`271d042`):

| Tela | Hash | Menu (permissão) | Arquivo |
|---|---|---|---|
| Relatórios | `#/relatorios` | `relatorio:export` | `js/views/relatorios.js` |
| Diretório, aba Execuções | `#/diretorio/execucoes` | `diretorio:sync` | `js/views/diretorio.js` |
| Diretório, aba Grupos | `#/diretorio/grupos` | `papel:assign` | `js/views/grupos.js` |

`#/diretorio` sem aba abre a primeira aba permitida, como a ficha da unidade (`views/unidade.js`). Nenhuma dependência nova, nenhum CSS novo além do que a tela precisar com os tokens existentes (`.panel`, `.tabs`, `.tbl-wrap`, `.filters`, `.pill`, `.btn`).

Reaproveitado: `api.js` (`chamar`, `ErroDaApi`), `html.js` (`html`, `montar`), `referencias.js` (nomes de distrito, área, tipo e `ROTULO_DO_STATUS`), `periodo.js` (`intervaloDoPeriodo` para o período da trilha), `paginas.js` (`buscarTodas` para juntar nome de grupo e mapeamento), `perms.js` (`tem`, `global`), `ui/estado.js`, `ui/form.js` (`campo`, `lerFormulario`, `mostrarErros`), `ui/format.js` (`fmtDataHora`), `ui/modal.js`, `ui/toast.js`.

## Rotas consumidas (contrato)
| Método e rota | Permissão | Uso na tela | Erros tratados | Requisitos |
|---|---|---|---|---|
| `POST /relatorios` | `relatorio:export` (+ `unidade:read` ou `auditoria:read`) | formulário | 403, 422 (campos), 503 | R1.2–R1.7 |
| `GET /relatorios?pagina&tamanho` | `relatorio:export` | lista e atualização | erro de tela | R2.1, R2.2 |
| `GET /relatorios/{id}` | `relatorio:export` | detalhe e integridade | 403, 404 | R3.1 |
| `GET /relatorios/{id}/download` | `relatorio:download` | botão Baixar | 403, 409, 503 (aviso) | R2.3, R2.4 |
| `GET /.well-known/relatorios-jwks.json` | pública | só link | – | R3.3 |
| `POST /admin/diretorio/sincronizar` | `diretorio:sync` | Sincronizar agora | 409 (aviso), 503 | R4.2, R4.3 |
| `GET /admin/diretorio/execucoes?pagina&tamanho` | `diretorio:sync` | lista e atualização | erro de tela | R4.4, R4.6 |
| `GET /admin/diretorio/execucoes/{id}` | `diretorio:sync` | detalhe | 404 | R4.5 |
| `GET /admin/diretorio/grupos?origem&busca&ativo&pagina&tamanho` | `papel:assign` | lista de grupos; `buscarTodas` para nomes | erro de tela | R5.1, R5.2 |
| `GET /admin/mapeamentos-grupo` | `papel:assign` | lista de mapeamentos | erro de tela | R5.2 |
| `GET /admin/papeis` | `papel:assign` | papéis e escopo exigido | erro no modal | R5.3 |
| `POST /admin/mapeamentos-grupo` | `papel:assign` | modal Mapear | 403, 409, 422 (campos) | R5.3, R5.4 |
| `DELETE /admin/mapeamentos-grupo/{id}` | `papel:assign` | Remover (com confirmação) | 403, 404 | R5.5 |

## Relatórios (`#/relatorios`, `views/relatorios.js`)
- **Cabeçalho:** "Relatórios", subtítulo "Peça um relatório; ele é gerado em segundo plano e fica disponível para baixar até a validade." (a validade é o `vence_em` da API).
- **Formulário** (`<form id="relForm">`, painel no topo):
  - Tipo (`tipo`, select): "Inventário de unidades" (com `unidade:read`) e "Trilha de auditoria" (com `auditoria:read`). Sem nenhum dos dois, o formulário some e fica um aviso "Seu perfil não pede nenhum tipo de relatório" (R1.3).
  - Formato (`formato`): CSV e XLSX (rádio ou select).
  - Inventário (R1.4): `distrito_id`, `area_tecnica_id`, `tipo_unidade_id` (selects das referências, "Todos" = ausente), `status` (`ROTULO_DO_STATUS`, "Todas" = ausente). Ids enviados como número.
  - Trilha (R1.5): `de` e `ate` (`<input type="date">`, obrigatórios), `acao` (texto, prefixo, máx. 50), `entidade_tipo` (texto, máx. 50). O período vai por `intervaloDoPeriodo('personalizado', de, ate)`: `de` = meia-noite de Recife do dia inicial, `ate` = meia-noite do dia seguinte ao final (exclusivo, como a API), ambos em `toISOString()`. Erro local do `periodo.js` aparece no campo `ate` sem chamar a API. O limite de 366 dias fica com a API (422).
  - Trocar o tipo mostra só os filtros dele.
  - **Erros 422** (R1.6): o `campo` da API vem como `trilha_auditoria.filtros.ate`, `filtros.distrito_id` ou `formato`; o front usa o último segmento como nome do campo em `mostrarErros`. Sem campo na tela, mostra o `detail` no `.err-summary` do formulário.
  - **503** (R1.7): `.err-summary` "A exportação de relatórios não está configurada neste servidor." **403:** o `detail` da API.
  - **202:** toast "Relatório pedido" e recarga da lista (o pedido aparece `pendente`).
- **Lista** (`<table data-ref="relatorios">`, R2.1): colunas Pedido em (`fmtDataHora(criado_em)`), Tipo, Formato, Filtros (texto: nomes das referências para o inventário, "dd/mm/aaaa a dd/mm/aaaa" e os textos para a trilha; "sem filtros"), Pedido por ("Você" se `solicitado_por === perfil.me.id`, senão "Outro usuário" com os 8 primeiros caracteres do id), Situação (pill: Pendente, Gerando, Concluído, Falhou, Vencido quando `vencido`), Pronto em, Tamanho (KB/MB), Validade (`vence_em`), Ações. Cada linha tem `data-id`.
  - **Ações:** "Detalhes" (sempre) e "Baixar" (só `concluido`, não `vencido` e `perfil.tem('relatorio:download')`, R2.4). Em `falhou`: a mensagem genérica (`erro`) na linha e "Pedir de novo", que reenvia `{tipo, formato, filtros}` do pedido (R2.5).
  - **Vazio:** "Nenhum relatório pedido ainda." **Erro:** `erro(falha)`.
  - **Paginação:** 20 por página, Anterior/Próxima como `views/historico.js`.
- **Atualização** (R2.2): `js/atualizacao.js` (novo, ~25 linhas) exporta `atualizarEnquanto({ alvo, pendente, recarregar })`. A cada 3 s, enquanto `alvo.isConnected` e `pendente()` for verdadeiro e não tiverem passado 2 min desde o último disparo, chama `recarregar()`. Um novo disparo (pedido, botão Atualizar, troca de página) recomeça os 2 min e cancela o anterior. Sair da tela desliga o laço porque `#view` é refeito pelo `desenharShell` e o `alvo` antigo sai do DOM. Botão "Atualizar" (`ic('refresh')`) sempre visível; o rótulo `aria-live` diz "Atualização automática ligada" ou "desligada".
- **Baixar** (R2.3): `GET /relatorios/{id}/download` e `location.assign(dados.url)`. A URL não é mostrada, nem guardada em variável de módulo, nem logada. O S3 responde `Content-Disposition: attachment`, então a tela não muda. 409, 403 e 503 viram toast de erro com o `detail` (R2.4).
- **Detalhes** (R3): modal com os dados do pedido (`GET /relatorios/{id}`, sempre fresco). Em `concluido`, o bloco "Integridade" (`data-ref="integridade"`): SHA-256, Algoritmo, `kid`, Assinatura (em `<code>`, quebra de linha livre), botão "Copiar integridade.json" (`navigator.clipboard.writeText(JSON.stringify(integridade, null, 2))`, toast "Copiado"; sem clipboard, seleciona o texto), o texto "Para conferir o arquivo, siga o roteiro `docs/operacao/verificar-relatorio.md` do repositório" e o link "Chaves públicas" para `/.well-known/relatorios-jwks.json` (`target="_blank" rel="noopener"`).

## Diretório (`#/diretorio/:aba`, `views/diretorio.js` e `views/grupos.js`)
- **Cabeçalho comum:** "Diretório", subtítulo "Usuários e grupos espelhados do LDAP e do provedor de identidade". `nav.tabs` com Execuções e Grupos, conforme a permissão (R4.1). Aba pedida sem permissão: "sem acesso".
- **Execuções** (`views/diretorio.js`, R4):
  - Botão "Sincronizar agora" (`ic('refresh')`). 202: toast "Sincronização iniciada" e recarga. 409: toast `wait` "Já há uma sincronização em andamento." (R4.3). 503: `.err-summary` "O LDAP não está configurado neste servidor." Botão desabilitado durante o pedido.
  - Tabela `data-ref="execucoes"`: Início, Fim, Situação (pill: Em andamento, Concluída, Falhou), Usuários (`+c ~a −d`, com `title` por extenso), Grupos (idem), Conflitos (número), Disparada por ("Você", "Automática" se `null`, ou id curto), ação "Detalhes". Vazio: "Nenhuma sincronização ainda. Clique em Sincronizar agora."
  - Detalhes (modal, `GET /execucoes/{id}`): contagens por extenso, tabela de conflitos (Tipo `email`/`username` → "E-mail repetido"/"Login repetido", `external_id`, Conta existente = id), e o `erro` genérico num `.banner`.
  - Atualização: a mesma `atualizarEnquanto`, com `pendente` = alguma execução `em_andamento` (R4.6).
- **Grupos** (`views/grupos.js`, R5):
  - Painel "Mapeamentos": tabela `data-ref="mapeamentos"` com Grupo (nome via `buscarTodas('/admin/diretorio/grupos', {ativo})` para `true` e `false`; sem par: "Grupo removido" e id curto), Papel (`rotuloDoPapel` de `perms.js`), Escopo ("Global" ou "Distrito 3", "Área 2", "Unidade 0197…"), ação "Remover". Vazio: "Nenhum grupo mapeado ainda."
  - Painel "Grupos do diretório": filtros Busca (`busca`, 1 a 100 caracteres, enviado ao mudar com 300 ms de espera), Origem (Todas, LDAP, OIDC), Situação (Ativos, Desativados → `ativo`). Tabela `data-ref="grupos"`: Nome, Origem, Membros ativos, Situação, ação "Mapear" (só grupo ativo). Paginação de 20.
  - **Mapear** (modal): título "Mapear grupo {nome}"; campo Papel (`campo` com opções de `GET /admin/papeis`, rótulo `nome`); ao escolher, o front mostra "Escopo exigido: {escopo_exigido}" e, se não for `global`, o campo `escopo_id` (texto, máx. 36, obrigatório, ajuda "Id do distrito ou da área (número) ou da unidade (UUID). A API confere se existe."). Envia `{grupo_id, papel, escopo_tipo: escopo_exigido, escopo_id|null}`. 201: fecha, toast "Grupo mapeado. Os membros ativos recebem o papel na próxima requisição." e recarrega os mapeamentos. 422: `mostrarErros` (campos `papel`, `escopo_id`, `grupo_id`→ geral). 409 e 403 (segregação de funções): `detail` no `.err-summary` do modal, que fica aberto (R5.4).
  - **Remover** (modal de confirmação): "Remover o mapeamento de {grupo} para {papel}? As atribuições que vieram dele saem; as atribuições diretas ficam." 204: toast e recarga (R5.5).

## Menu e rotas (`perms.js`, `main.js`)
- `itensDoMenu`, no bloco de gestão: `['#/relatorios', 'download', 'Relatórios', 'relatorios']` depois de Qualidade/Histórico (com `relatorio:export`), e `['#/diretorio', 'refresh', 'Diretório', 'diretorio']` antes de Papéis (com `diretorio:sync` ou `papel:assign`).
- `main.js`: `rota('relatorios', tela('relatorios', p => p.tem('relatorio:export'), ...))`, `rota('diretorio', ...)` e `rota('diretorio/:aba', ...)` com `p.tem('diretorio:sync') || p.tem('papel:assign')`.
- Consequência (P3): o Admin TI passa a abrir em `#/diretorio` (012/R3.5); `test_perfis.py` muda os quadros `MENU` e `INICIO` do ADMIN_TI.

## Modelo de dados / migrações
Nenhum.

## Fluxo
```
Relatórios: abrir → [referências ∥ GET /relatorios] → formulário + lista
  enviar → POST /relatorios (202) → recarregar lista → atualizarEnquanto(pendente|gerando)
  Baixar → GET …/download → location.assign(url) → o navegador baixa do s3.<host>
Diretório: abrir → aba permitida → Execuções: GET /execucoes → Sincronizar → POST (202|409) → atualizarEnquanto(em_andamento)
                                  Grupos: [GET /mapeamentos ∥ grupos (buscarTodas) ∥ GET /grupos paginado] → Mapear → POST (201) → recarregar
```

## Segurança
- Esconder botão não é segurança (012/R3.4): toda ação passa pela API, e 403 vira mensagem.
- Tudo que vem da API passa por `html` (escape). `escopo_id`, `busca`, `acao` e `entidade_tipo` só vão como JSON ou `URLSearchParams`.
- A URL pré-assinada é credencial de 5 minutos (D005-1): só vai para `location.assign`, sem DOM, log ou estado.
- Clipboard só com a integridade, que é pública para quem vê o pedido.
- CSP do Caddy inalterada: navegação para `s3.<host>` não é `connect-src`; o JWKS é do mesmo domínio.
- Nenhum nome ou e-mail de pessoa nas telas: a API devolve ids (LGPD).

## Decisões e alternativas
- **D014-1 Atualização limitada** (3 s, 2 min, só com pendente) em vez de SSE/WebSocket: as rotas já existem e o laboratório tem 2 vCPU.
- **D014-2 Escopo do mapeamento por id digitado** (P1): o Admin TI não tem `unidade:read`. Alternativa recusada: emendar a matriz da 003 no prazo do freeze.
- **D014-3 Copiar `integridade.json`** em vez de só a assinatura (P2): é o arquivo que o roteiro lê.
- **D014-4 Detalhe em modal**, não em rota própria: menos código e o padrão de `historico.js` (detalhe do evento).
- **D014-5 Diretório em duas abas por rota** (`#/diretorio/:aba`), como a ficha da unidade.

## Riscos
- **Subida mais lenta da suíte E2E** (+`ldap`, `s3`, `s3-init`): ~30 s a mais por execução; aceitável.
- **Download no Playwright**: o host `s3.localhost:18444` precisa resolver para o loopback (Chromium resolve `*.localhost`) e `SGS_PUBLIC_S3_URL` tem de apontar a porta da suíte; senão a URL pré-assinada falha. Já é o que `tests/e2e/test_export_s3.py` faz.
- **Sincronização no E2E muda usuários** do banco descartável: os usuários do seed demo são locais e não são tocados.
- **Segregação de funções (403) no mapeamento** não acontece com o Admin TI do seed (conta local, sem grupo): o teste simula a resposta com `page.route` (R6.2).

- *Notas de implementação (26/11/2026, integração):*
  - o `s3-init` saiu do `up --wait` da suíte (o compose 5.7 dá como falha um one-shot que termina antes da checagem); a fixture espera o exit 0, como `tests/e2e/test_export_s3.py`;
  - o SeaweedFS de laboratório ganhou `-master.volumeSizeLimitMB=64` em `docker/compose.yml`: o teto de volumes é o disco livre dividido pelo tamanho do volume (1 GiB), e com ~5 GB livres o bucket ficava sem volume depois das outras suítes ("Not enough data nodes found"), e a geração falhava. O laboratório na AWS não sobe o `s3` (perfil `seaweedfs`), então não muda.

## Estratégia de testes
- `tests/e2e_front/conftest.py`: o `up` passa a subir `proxy ldap s3 s3-init`, e `AMBIENTE_COMPOSE` ganha `SGS_PUBLIC_S3_URL=https://s3.localhost:18444`. Nada mais muda.
- `tests/e2e_front/test_relatorios.py` (novo): menu por papel (R1.1); Diretoria sem "Trilha de auditoria" (R1.3); pedido de inventário CSV pelo Gestor de Dados aparece `pendente` e vira `concluido` sem clique (R1.2, R2.2); Baixar dispara um download `.csv` cujo SHA-256 é o do bloco Integridade (R2.3, R3.1); "Copiar integridade.json" copia o objeto da API (R3.2, com permissão de clipboard no contexto); trilha com período > 366 dias mostra o erro no campo (R1.6); laço para ao sair da tela (sem `GET /relatorios` por 4 s depois de navegar, R2.2); estados simulados: 503 no pedido (R1.7), `falhou` com "Pedir de novo" (R2.5), 409 no download (R2.4).
- `tests/e2e_front/test_diretorio.py` (novo): menu e abas do Admin TI, sem acesso para os demais (R4.1); Sincronizar agora cria execução que conclui sem clique e mostra contagens (R4.2, R4.4, R4.6); segundo clique logo em seguida dá o aviso de 409 ou a execução já concluída (o teste aceita os dois, o 409 é coberto simulado, R4.3); detalhe com contagens (R4.5); grupos do `seed.ldif` listados e buscados (R5.1); mapear um grupo para DIRETORIA global aparece nos mapeamentos com o nome do grupo (R5.2, R5.3); escopo inválido dá erro no campo (R5.4); remover tira da lista (R5.5); 403 de segregação simulado mostra a mensagem da API (R5.4).
- `tests/e2e_front/test_perfis.py`: menu e início do Admin TI; menu de quem tem `relatorio:export`.
- `make check` (rápido) não roda estas suítes (`slow`); cada tarefa registra também a execução `uv run pytest -m slow tests/e2e_front/<arquivo>`.
