# sgs-api · Arquitetura inicial do backend

API da Plataforma de Governança de Dados de Saúde · Secretaria de Saúde do Recife · Grupo 01 (CESAR School, CS018).

Esta pasta já está organizada como a raiz do futuro repositório: documentação, specs e steering primeiro, código depois (spec-driven development).

## Comece por aqui
| Documento | Para quê |
|---|---|
| [docs/research/01-pesquisa-stack-backend.md](docs/research/01-pesquisa-stack-backend.md) | Pesquisa da stack: FastAPI, auth, RBAC, LDAP, OIDC, S3, ferramentas |
| [docs/architecture/arquitetura-conceitual.md](docs/architecture/arquitetura-conceitual.md) | Papéis, recursos, matriz de permissões, componentes, fluxos, rotas |
| [docs/architecture/modelo-dados.md](docs/architecture/modelo-dados.md) | Tabelas e relacionamentos |
| [docs/adr/](docs/adr/) | Decisões arquiteturais (ADR-0001 a 0006) |
| [specs/](specs/) | Specs SDD 001 a 010 (requisitos EARS, design, tarefas), rastreabilidade e calendário |
| [AGENTS.md](AGENTS.md), [CLAUDE.md](CLAUDE.md), [steering/](steering/) | Contexto e regras para agentes de código |
| [.claude/commands/](.claude/commands/) | Comandos do fluxo SDD no Claude Code |
| [.github/](.github/) | CI e template de PR |

## Ordem de implementação sugerida
Ver o calendário em [specs/README.md](specs/README.md#ordem-e-calendário-sugeridos): fundação e login primeiro, depois RBAC e cadastro, validação e dados de demonstração, histórico e dashboard, e por fim LDAP/OIDC e exportação S3.

## Pendências para o grupo
- Confirmar FastAPI e atualizar o Documento de Arquitetura da Atividade 5, que ainda diz Node.js (ADR-0001).
- Aprovar ou ajustar a matriz de papéis × permissões.
- Definir o dono humano de cada spec.
- Definir o repositório GitHub.
