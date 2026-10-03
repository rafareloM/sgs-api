# 008 · Histórico de alterações · Requisitos

- Status: Rascunho
- Rastreia: RF-08, RS-05, RS-09; critério 6.1 "alteração aparece no histórico com autor, data e hora"; pilar Controle

## Contexto
A spec 001 cria a trilha imutável (`audit_log`) e o serviço de gravação. Esta spec entrega a **consulta** da trilha: o histórico de uma unidade, a trilha geral para auditores e a verificação de integridade da cadeia de hash (o protótipo já mostra o hash por evento).

## Fora do escopo
- Desfazer alteração a partir do histórico.
- Expurgo automático após 2 anos (manual nesta versão).

## Histórias e critérios

### R1. Histórico da unidade
Como gestor, quero ver o que mudou numa unidade, quando e por quem.

- R1.1 QUANDO um usuário com `auditoria:read` no escopo da unidade consulta `GET /unidades/{id}/historico`, o sistema DEVE listar os eventos da unidade (incluindo equipamentos e serviços) do mais recente ao mais antigo, paginados.
- R1.2 Cada evento DEVE mostrar data e hora (fuso de Recife na resposta), autor (nome e papel no momento), ação e a lista `{campo, de, para}` com rótulos legíveis.
- R1.3 O sistema DEVE filtrar o histórico por período, autor e campo.
- R1.4 SE o usuário não tiver o escopo, ENTÃO o sistema DEVE responder 403.

### R2. Trilha geral
Como Auditor, quero consultar todos os eventos, inclusive de acesso.

- R2.1 QUANDO um usuário com `auditoria:read` global consulta `GET /auditoria/eventos`, o sistema DEVE listar eventos de negócio com filtros por período, ação, entidade e autor.
- R2.2 Eventos de acesso (`auth.*`, `acesso.negado`) DEVEM aparecer somente para quem tem `auditoria:read_acessos`.
- R2.3 O sistema DEVE mascarar valores marcados como sensíveis.

### R3. Integridade
- R3.1 QUANDO um Auditor chama `POST /auditoria/verificar` com um período, o sistema DEVE recalcular a cadeia de hash e responder `integra: true` ou o primeiro evento onde a cadeia quebra.
- R3.2 A consulta de evento individual DEVE exibir `hash` e `prev_hash`.

### R4. Retenção
- R4.1 O sistema DEVE manter eventos por pelo menos 2 anos (partições mensais nunca apagadas antes disso).

## Perguntas em aberto
- O Gestor de Unidade deve ver o histórico completo da própria unidade ou apenas as próprias alterações? (padrão adotado: completo)
