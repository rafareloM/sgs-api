# ADR-0006: Spec-driven development e esteira agêntica

- Status: Proposto
- Data: 2026-10-03
- Requisitos relacionados: RNF-06, critério 6.2 (documentação coerente com o construído), registro de uso de IA

## Contexto
O grupo quer desenvolver com agentes de IA (Claude Code e similares) sem perder o controle das decisões, e a Entrega Final cobra documentação coerente com o código e registro claro do uso de IA. O risco já mapeado é "documentação deixada para o fim".

## Decisão
- Toda funcionalidade nasce como spec em `specs/NNN-nome/` com três arquivos: `requirements.md` (critérios EARS rastreados aos RF/RS), `design.md` e `tasks.md`.
- Arquivos de steering (`AGENTS.md`, `CLAUDE.md`, `steering/*.md`) dão aos agentes o contexto do produto, da stack, da estrutura e das regras de segurança.
- Cada fase tem um portão humano: requisitos aprovados → design aprovado → tarefas aprovadas → implementação por tarefa com testes → revisão de PR por um integrante.
- O CI bloqueia merge sem testes verdes, lint, tipos, regras de arquitetura e contrato OpenAPI atualizado.
- Commits feitos com ajuda de agente levam o trailer `Co-Authored-By`, o que alimenta o registro de uso de IA.

## Consequências
- Documentação é produzida antes e junto do código, não no fim.
- Mais cerimônia por funcionalidade; compensada por menos retrabalho.

## Alternativas consideradas
- Desenvolvimento livre com IA ("vibe coding"): rápido, mas gera código sem rastreabilidade e documentação divergente.
