# Specs (spec-driven development)

Cada funcionalidade tem uma pasta `NNN-nome/` com três arquivos, escritos e aprovados nessa ordem:

1. `requirements.md`: histórias e critérios de aceitação no formato EARS, cada um com ID (`R1.1`) e rastreado a RF/RNF/RS.
2. `design.md`: como será construído (rotas, modelos, fluxos, decisões, riscos). Referencia os IDs dos requisitos.
3. `tasks.md`: tarefas pequenas, ordenadas, cada uma com os requisitos que cobre e o teste que prova que está pronta.

O status fica no cabeçalho de cada arquivo: `Rascunho` → `Em revisão` → `Aprovado`. Um agente só implementa tarefas de uma spec com os três arquivos `Aprovado`.

| Spec | Tema | Origem | Status |
|---|---|---|---|
| [001-fundacao](001-fundacao/) | Esqueleto da API, config, banco, erros, logs, auditoria base, CI | base para todos | Rascunho |
| [002-autenticacao](002-autenticacao/) | Login local, 2FA TOTP, tokens, sessões | obrigatório: RBAC (autenticação) | Rascunho |
| [003-rbac](003-rbac/) | Papéis, permissões, escopo, `/me`, administração | obrigatório: RBAC | Rascunho |
| [004-diretorio-ldap-oidc](004-diretorio-ldap-oidc/) | Bind e sincronização LDAP, login OIDC, grupos | obrigatório: LDAP/OIDC | Rascunho |
| [005-exportacao-relatorios-s3](005-exportacao-relatorios-s3/) | Relatórios CSV/XLSX, STS, S3, URL pré-assinada | obrigatório: exportação para nuvem | Rascunho |
| [006-cadastro-unidades](006-cadastro-unidades/) | Unidades, equipamentos, serviços, busca, referências | MVP: cadastro, consulta, atualização | Rascunho |
| [007-validacao-dados](007-validacao-dados/) | Regras fixas e configuráveis, 422 claro, pendências | MVP: validação automática | Rascunho |
| [008-historico-alteracoes](008-historico-alteracoes/) | Histórico por unidade, trilha geral, integridade | MVP: histórico (auditoria) | Rascunho |
| [009-dashboard](009-dashboard/) | Agregados da rede e da qualidade dos dados | MVP: dashboard básico | Rascunho |
| [010-dados-demonstracao](010-dados-demonstracao/) | Seed de Saúde Mental, usuários por papel, conversor da planilha | pendência 6 (massa de dados) | Rascunho |

## Rastreabilidade requisito → spec

| Requisito | Specs |
|---|---|
| RF-01 Cadastro centralizado | 006 |
| RF-02 Equipamentos | 006 |
| RF-03 Validação | 007 |
| RF-04 Aprovação | fora do MVP (papéis e permissões em 003) |
| RF-05 CNES | fora do MVP |
| RF-06 Dashboards | 009 |
| RF-07 Relatórios | 005 (parcial) |
| RF-08 Histórico | 001 (gravação), 008 (consulta) |
| RF-09 Busca/filtros | 006 |
| RF-10 Notificações | fora do MVP |
| RS-01 Autenticação | 002, 004 |
| RS-02 RBAC | 003 (aplicado em 005 a 009) |
| RS-03 / RS-04 Criptografia | 001, 002, 004, 005 |
| RS-05 Auditoria | 001, 002, 008 |
| RS-08 Validação de entrada | 001, 007 |
| RS-09 Monitoramento | 002, 008 |
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
