# Steering · Fluxo SDD e esteira agêntica

## Ciclo de uma funcionalidade

```mermaid
flowchart LR
  A[Pedido / requisito] --> B[/spec-requisitos/]
  B --> G1{Humano aprova\nrequirements.md}
  G1 --> C[/spec-design/]
  C --> G2{Humano aprova\ndesign.md}
  G2 --> D[/spec-tarefas/]
  D --> G3{Humano aprova\ntasks.md}
  G3 --> E[/spec-implementar Tn/]
  E --> F[make check verde]
  F --> P[PR com spec e tarefa]
  P --> CI[CI completo]
  CI --> R[/spec-revisar/ + revisão humana]
  R --> M[Merge]
  M -->|próxima tarefa| E
```

| Fase | Quem produz | Saída | Portão |
|---|---|---|---|
| Requisitos | agente a partir do pedido e dos documentos | `requirements.md` em EARS, IDs rastreados a RF/RS | Dono da spec aprova |
| Design | agente | `design.md` com rotas, modelo, fluxos, riscos, testes | Dono da spec + 1 integrante aprovam |
| Tarefas | agente | `tasks.md`, tarefas de até ~300 linhas de diff, cada uma com teste | Dono aprova |
| Implementação | agente, uma tarefa por vez, TDD | código + testes + `[x]` na tarefa | `make check` verde |
| PR | agente abre, humano revisa | PR citando `NNN/Tn` | CI verde + 1 aprovação humana |

## Regras
- A spec é a fonte da verdade. Código que diverge da spec é bug em um dos dois: corrija o que estiver errado no mesmo PR.
- Mudanças de requisito no meio do caminho: edite `requirements.md`, volte o status para `Em revisão`, ajuste design e tarefas.
- Cada spec tem um **dono humano** (integrante do grupo). Isso cumpre "cada integrante tem entregas rastreáveis".
- O agente nunca marca a própria spec como `Aprovado`.
- Uso de IA: o trailer `Co-Authored-By` nos commits e a seção "Uso de IA" do template de PR alimentam o "Registro de uso de IA" da entrega final.

## O que o CI garante
1. `uv sync --frozen` (dependências travadas).
2. `ruff check` e `ruff format --check`.
3. `mypy`.
4. `lint-imports` (camadas).
5. `pytest` unidade + integração (Postgres via service container).
6. Teste de arquitetura (rotas protegidas).
7. `contracts/openapi.yaml` igual ao gerado pelo código.
8. `bandit` e `pip-audit`.
9. Smoke do `docker compose` (`/health/ready`).

## Rastreabilidade
RF/RS (documento de requisitos) → `Rx.y` (requirements.md) → seção do design → `Tn` (tasks.md) → teste nomeado → commit `(NNN/Tn)` → PR.
