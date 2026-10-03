---
description: Escreve design.md de uma spec com requisitos aprovados
argument-hint: <NNN-nome>
---
Escreva `specs/$1/design.md` a partir do template.

1. Confirme que `specs/$1/requirements.md` está `Status: Aprovado`. Se não estiver, pare e avise.
2. Leia `steering/tech.md`, `steering/structure.md`, `steering/security.md`, `docs/architecture/` e os ADRs.
3. Para cada rota: método, caminho, permissão, entrada, saída, erros e IDs de requisito.
4. Descreva migrações, portas/adaptadores, fluxo, decisões com alternativas, riscos e estratégia de testes.
5. Se a decisão contrariar um ADR ou a stack, proponha um novo ADR em vez de seguir em frente.
6. Todo requisito `Rx.y` deve aparecer em pelo menos uma seção. Liste os que ficaram sem cobertura.
7. Deixe `Status: Rascunho`.
