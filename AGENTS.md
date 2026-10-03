# AGENTS.md · sgs-api

Instruções para qualquer agente de código (Claude Code, Codex, Copilot, Cursor...) que trabalhe neste repositório. Humanos também devem ler.

## O que é
API (FastAPI/Python) da Plataforma de Governança de Dados de Saúde da Secretaria de Saúde do Recife. Projeto acadêmico do Grupo 01 (CESAR School, CS018), com cliente real. Leia `steering/product.md` antes de qualquer tarefa.

## Contexto obrigatório (leia conforme a tarefa)
| Arquivo | Quando ler |
|---|---|
| `steering/product.md` | Sempre: domínio, papéis, escopo do MVP |
| `steering/tech.md` | Sempre: stack, versões, comandos |
| `steering/structure.md` | Antes de criar ou mover arquivos |
| `steering/security.md` | Antes de mexer em auth, RBAC, dados, logs, integrações |
| `steering/sdd-workflow.md` | Antes de começar qualquer funcionalidade |
| `steering/testing.md` | Antes de escrever testes |
| `specs/NNN-*/` | A spec da tarefa em andamento |
| `docs/architecture/` e `docs/adr/` | Quando a decisão afetar arquitetura |

## Regras inegociáveis
1. **Nada de código sem spec aprovada.** Implemente apenas tarefas de `specs/*/tasks.md` cujos três arquivos estejam com `Status: Aprovado`. Se a tarefa não existir, proponha a mudança na spec primeiro.
2. **Uma tarefa por vez, com teste.** Escreva o teste citado em "Pronto quando", veja-o falhar, implemente, veja-o passar.
3. **Não invente requisito.** Se a spec estiver ambígua, pare e registre a dúvida em "Perguntas em aberto" da spec.
4. **Toda rota declara permissão** (`require("recurso:acao")`) ou está na lista de rotas públicas. Deny by default.
5. **Toda alteração de dado de negócio grava auditoria na mesma transação.**
6. **Nunca** logar ou commitar senha, token, segredo, chave ou `.env`.
7. **Camadas:** `domain` não importa FastAPI, SQLAlchemy, boto3, ldap3 nem Authlib.
8. **Mudou o contrato da API?** Atualize `contracts/openapi.yaml` (`make openapi`) no mesmo PR.
9. **Decisão arquitetural nova** vira ADR em `docs/adr/`.
10. Rode `make check` antes de declarar uma tarefa pronta.

## Comandos
```bash
uv sync                      # instala dependências
make check                   # lint + format + tipos + arquitetura + testes rápidos
make test-all                # inclui integração (precisa de Docker)
make openapi                 # regenera contracts/openapi.yaml
docker compose -f docker/compose.yml up -d   # ambiente completo
uv run alembic upgrade head  # migrações
```

## Idioma
Código, nomes de variáveis e commits em inglês técnico quando for termo de programação; domínio em português (ex.: `health_units` no banco, mas `unidade` em rotas e mensagens). Mensagens ao usuário em português. Documentação em português.

## Commits e PRs
- Conventional Commits: `feat(identity): login LDAP (004/T5)`. Sempre cite spec e tarefa.
- Commits com ajuda de agente levam o trailer `Co-Authored-By:` do agente (alimenta o registro de uso de IA exigido na entrega final).
- PR usa `.github/pull_request_template.md` e precisa de revisão de um integrante humano.
