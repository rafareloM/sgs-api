# Specs (spec-driven development)

Cada funcionalidade tem uma pasta `NNN-nome/` com três arquivos, escritos e aprovados nessa ordem:

1. `requirements.md`: histórias e critérios de aceitação no formato EARS, cada um com ID (`R1.1`) e rastreado a RF/RNF/RS.
2. `design.md`: como será construído (rotas, modelos, fluxos, decisões, riscos). Referencia os IDs dos requisitos.
3. `tasks.md`: tarefas pequenas, ordenadas, cada uma com os requisitos que cobre e o teste que prova que está pronta.

O status fica no cabeçalho de cada arquivo: `Rascunho` → `Em revisão` → `Aprovado`. Um agente só implementa tarefas de uma spec com os três arquivos `Aprovado`.

As specs 008, 009 e 010 e a emenda T21–T22 da 011 foram implementadas antes do portão humano (consolidação de 09/11/2026) e aprovadas na regularização do mesmo dia pelo dono, Vinicius (ViniciusVbm), que também assumiu a 003 (`steering/sdd-workflow.md` § Dono da spec). Aprovações, divergências resolvidas e pendências funcionais estão em [`../docs/relatorios/REGULARIZACAO_GOVERNANCA_SPECS.md`](../docs/relatorios/REGULARIZACAO_GOVERNANCA_SPECS.md).

| Spec | Tema | Origem | Status |
|---|---|---|---|
| [001-fundacao](001-fundacao/) | Esqueleto da API, config, banco, erros, logs, auditoria base, CI | base para todos | Aprovado |
| [002-autenticacao](002-autenticacao/) | Login local, 2FA TOTP, tokens, sessões | obrigatório: RBAC (autenticação) | Aprovado |
| [003-rbac](003-rbac/) | Papéis, permissões, escopo, `/me`, administração | obrigatório: RBAC | Aprovado (Rafael); emenda de `dashboard:read` aprovada (Vinicius, 09/11); dono: Vinicius |
| [004-diretorio-ldap-oidc](004-diretorio-ldap-oidc/) | Bind e sincronização LDAP, login OIDC, grupos | obrigatório: LDAP/OIDC | Requisitos, design e tarefas aprovados (Rafael, 24/11; G2 só do dono, exceção de 24/11); em implementação em três frentes com a outra spec (`docs/implementacao/`); donos: Vinicius e Rafael |
| [005-exportacao-relatorios-s3](005-exportacao-relatorios-s3/) | Relatórios CSV/XLSX, STS, S3, URL pré-assinada | obrigatório: exportação para nuvem | Requisitos, design e tarefas aprovados (Rafael, 24/11; G2 só do dono, exceção de 24/11); em implementação em três frentes com a outra spec (`docs/implementacao/`); donos: Vinicius e Rafael |
| [006-cadastro-unidades](006-cadastro-unidades/) | Unidades, equipamentos, serviços, busca, referências | MVP: cadastro, consulta, atualização | Aprovado |
| [007-validacao-dados](007-validacao-dados/) | Regras fixas e configuráveis, 422 claro, pendências | MVP: validação automática | Rascunho |
| [008-historico-alteracoes](008-historico-alteracoes/) | Histórico por unidade, trilha geral, integridade | MVP: histórico (auditoria) | Aprovado (Vinicius, 09/11); T6 concluída (09/11) |
| [009-dashboard](009-dashboard/) | Agregados da rede e da qualidade dos dados | MVP: dashboard básico | Aprovado (Vinicius, 09/11); faltam T2b (cache) e T3 (desempenho) |
| [010-dados-demonstracao](010-dados-demonstracao/) | Seed de Saúde Mental, usuários por papel, conversor da planilha | pendência 6 (massa de dados) | Aprovado (Vinicius, 09/11); falta T3 (planilha do cliente) |
| [011-recursos-banco-dados](011-recursos-banco-dados/) | Índices, consultas avançadas, views, funções, procedimentos, triggers, log do banco, segurança no SGBD | disciplina de Banco de Dados (Segunda Parte, 13/11) | Aprovado (Rafael, T1–T20); emenda T21–T22 aprovada (Vinicius, 09/11); dono: Vinicius |
| [012-frontend](012-frontend/) | Interface real a partir do protótipo HTML: autenticação, perfis, unidades, serviços, qualidade, histórico | Entrega 11 (21/11) | Aprovado: requisitos (Vinicius, 09/11), design (Vinicius, Igor Fugagnoli e Erick Sanches, 10/11) e tarefas (Vinicius, 10/11); emenda funcional 1 (R5.5) aguarda o G1 do dono; emenda funcional 2 aprovada na sessão de 10/11, com a confirmação no PR pendente com o dono |
| [013-trilha-auditoria-reforco](013-trilha-auditoria-reforco/) | Origem, resultado, IP/UA confiável, verificação consistente com cabeça e âncora, `db_change_log` imutável, cobertura, detalhe e histórico com RBAC, retenção e backup | lacunas A–I da auditoria técnica da trilha (11/11) | Aprovado (Vinicius, proprietário, 11/11; G1, G2 e G3 só do dono, pela exceção pontual de `steering/sdd-workflow.md`); implementação na branch `feat/013-trilha-auditoria`; emendas com nota de referência no design da 001 (canonicalização) e no da 011 (`vw_unit_history`) |
| [014-frontend-diretorio-relatorios](014-frontend-diretorio-relatorios/) | Telas de Relatórios (005) e Diretório: execuções da sincronização e mapeamentos grupo→papel (004, 003) | mapa #25; freeze de 28/11 | Aprovado (Rafael, 26/11; G2 só do dono, exceção de 26/11); dono: Rafael |

## Rastreabilidade requisito → spec

| Requisito | Specs |
|---|---|
| RF-01 Cadastro centralizado | 006 |
| RF-02 Equipamentos | 006 |
| RF-03 Validação | 007 |
| RF-04 Aprovação | fora do MVP (papéis e permissões em 003) |
| RF-05 CNES | fora do MVP |
| RF-06 Dashboards | 009 |
| RF-07 Relatórios | 005 (parcial), 014 (tela) |
| RF-08 Histórico | 001 (gravação), 008 (consulta), 013 (reforço) |
| RF-09 Busca/filtros | 006 |
| RF-10 Notificações | fora do MVP |
| RS-01 Autenticação | 002, 004 |
| RS-02 RBAC | 003 (aplicado em 005 a 009) |
| RS-03 / RS-04 Criptografia | 001, 002, 004, 005 |
| RS-05 Auditoria | 001, 002, 008, 013 |
| RS-08 Validação de entrada | 001, 007 |
| RS-09 Monitoramento | 002, 008, 013 |
| Disciplina de Banco de Dados (Segunda Parte e Etapa 06) | 011 (CRUD de 4 tabelas pela 006) |
| Critérios 6.1 da Entrega Final | 002, 003, 006, 007, 008, 009, 001 (compose) |

## Ordem e calendário sugeridos

| Semana | Specs | Marco |
|---|---|---|
| 06/10 a 12/10 | 001, 002 | API sobe no compose com login + 2FA |
| 13/10 a 19/10 | 003, 006 (T1 a T5) | Cadastro com RBAC; base para o protótipo de alta fidelidade (17/10) |
| 20/10 a 26/10 | 007, 010 | Validação e dados para os testes de usabilidade (24/10) |
| 27/10 a 02/11 | 008, 009, 006 (resto) | Fluxo central completo |
| 03/11 a 07/11 | 004, 005 | Requisitos das disciplinas; prazo do MVP (07/11) |

## Formato EARS (resumo)

| Tipo | Molde |
|---|---|
| Sempre | O sistema DEVE ... |
| Evento | QUANDO <gatilho>, o sistema DEVE ... |
| Estado | ENQUANTO <estado>, o sistema DEVE ... |
| Indesejado | SE <condição indesejada>, ENTÃO o sistema DEVE ... |
| Opcional | ONDE <funcionalidade habilitada>, o sistema DEVE ... |
