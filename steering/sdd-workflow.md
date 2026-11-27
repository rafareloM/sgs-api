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
| PR | agente abre, humano revisa | PR citando `NNN/Tn` | CI verde + 1 aprovação humana (PR do administrador: revisão por agente; sem Actions, `make check` local; ADR-0008) |

## Exceção provisória: prazo de Banco de Dados (Rafael, 07/11/2026)
Para as specs **003, 006 e 011**, por causa da entrega da disciplina de Banco de Dados em 13/11/2026, o Rafael (dono das specs e administrador do repositório) aprova sozinho os portões de design e de tarefas, sem o segundo integrante. Vale só para essas três specs; as demais seguem a tabela acima. A exceção sai quando a 011 for entregue.

A exceção é pessoal: não passa a quem assumir essas specs depois. Desde a transferência da 003 e da 011 para o Vinicius (09/11/2026), as emendas delas seguem a tabela acima, salvo a exceção pontual abaixo.

## Exceção pontual: regularização de 09/11/2026 (Vinicius)
Os designs revistos na regularização das specs 008, 009, 010 e 011 (itens V1 a V5 de `docs/relatorios/REGULARIZACAO_GOVERNANCA_SPECS.md`) foram aprovados só pelo dono, sem o segundo integrante. Vale só para essa regularização e já se esgotou. A regra geral da tabela (dono + 1 integrante no design) não mudou.

## Exceção pontual: spec 012, tarefa T1 (Vinicius, 10/11/2026)
- **O que permite:** implementar só a **T1** da spec 012 antes do G2 (design) e do G3 (tarefas). A T1 é a entrega do front pelo Caddy: `Caddyfile`, volume no compose, `index.html` mínimo e o teste de entrega.
- **Quem decidiu:** o dono da spec, Vinicius, em 10/11/2026, na sessão de trabalho registrada no PR #4.
- **Motivo:** a T1 é infraestrutura e não depende das decisões de UX do design, e a revisão independente do design (Igor Fugagnoli, suplente Erick Sanches) ainda não aconteceu.
- **Condições:**
  - o G2 continua obrigatório e é revisado em paralelo no PR #4;
  - o PR **não** é integrado à `main` antes do registro do G2;
  - se o revisor pedir mudança que afete a T1, ela é refeita;
  - as T2 a T23 seguem a regra geral (requisitos, design e tarefas `Aprovado`).
- **Alcance:** vale só para a T1 da 012 e não se estende a outras tarefas nem a outras specs.

## Exceção pontual: spec 013, aprovação só do proprietário (Vinicius, 11/11/2026)
- **O que permite:** que os três portões da spec 013 (G1, G2 e G3) sejam aprovados só pelo dono, Vinicius (ViniciusVbm), sem o segundo integrante que a tabela exige no G2.
- **Quem decidiu:** o próprio Vinicius, proprietário e único responsável pelo projeto, na sessão de trabalho de 11/11/2026. A aprovação foi registrada pelo agente por autorização expressa dada nessa sessão. O agente não aprova nada em nome de ninguém.
- **Motivo:** não há segundo integrante disponível para a revisão do design da 013. A falta da revisão independente fica registrada como limitação no `Status:` do `design.md` da 013.
- **Alcance:** vale só para a 013. A regra geral da tabela não muda para as demais specs.

## Exceção pontual: specs 004 e 005, design aprovado só pelo dono (Rafael, 24/11/2026)
- **O que permite:** que o G2 (design) das specs 004 e 005 seja aprovado só pelo dono, Rafael (rafareloM), sem o segundo integrante que a tabela exige.
- **Quem decidiu:** o próprio Rafael, dono das duas specs e responsável pelo projeto, na sessão de trabalho de 24/11/2026. A decisão foi registrada pelo agente por autorização expressa dada nessa sessão. O agente não aprova nada em nome de ninguém.
- **Contexto:** prazos de 28/11/2026 (code freeze) e 05/12/2026 (SR2), em `docs/relatorios/PENDENCIAS_EXTERNAS.md`. A falta da revisão independente fica registrada como limitação no `Status:` do `design.md` das duas specs.
- **Alcance:** vale só para o G2 das specs 004 e 005. O G1 e o G3 já são só do dono pela tabela. A regra geral não muda para as demais specs.

## Exceção pontual: spec 014, design aprovado só pelo dono (Rafael, 26/11/2026)
- **O que permite:** que o G2 (design) da spec 014 seja aprovado só pelo dono, Rafael (rafareloM), sem o segundo integrante que a tabela exige.
- **Quem decidiu:** o próprio Rafael, dono da spec e responsável pelo projeto, na sessão de trabalho de 26/11/2026. A decisão foi registrada pelo agente por autorização expressa dada nessa sessão. O agente não aprova nada em nome de ninguém.
- **Contexto:** code freeze de 28/11/2026. A falta da revisão independente fica registrada como limitação no `Status:` do `design.md` da 014.
- **Alcance:** vale só para o G2 da spec 014. A regra geral não muda para as demais specs.

## Dono da spec: atribuição e transferência
- O dono fica numa linha do cabeçalho do `requirements.md`: `- Dono humano: <nome> (<login>)`. Design e tarefas seguem o dono dos requisitos.
- Spec sem dono registrado fica com o responsável pelo projeto até alguém assumir. Responsável pelo projeto desde 09/11/2026: Vinicius (ViniciusVbm). Também responsável, com os mesmos poderes: Rafael (rafareloM), administrador do repositório, registrado em 24/11/2026 por declaração dele na sessão de trabalho (registro do agente).
- Transferir é trocar essa linha por `- Dono humano: <novo> (<login>), desde <data>; antes: <anterior>`, num commit ou PR que diga o motivo. Quem transfere é o dono atual ou o responsável pelo projeto. Não há outro passo.
- Aprovações e decisões já registradas continuam com o nome e a data de quem as deu. O novo dono não as refaz nem assina nada com data retroativa.
- Os portões que estavam pendentes passam ao novo dono, com as mesmas regras da tabela.

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
