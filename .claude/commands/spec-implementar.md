---
description: Implementa uma tarefa de uma spec aprovada, com TDD
argument-hint: <NNN-nome> <Tn>
---
Implemente a tarefa $2 de `specs/$1/tasks.md`.

1. Confirme que os três arquivos da spec estão `Aprovado`. Se não, pare.
2. Leia a tarefa, os requisitos que ela cita e as seções correspondentes do design.
3. Escreva primeiro o teste indicado em "Pronto quando", com docstring citando `$1/Rx.y`. Rode e confirme que falha.
4. Implemente o mínimo para o teste passar, respeitando `steering/structure.md` e `steering/security.md`.
5. Rode `make check`. Corrija até ficar verde.
6. Se a rota/contrato mudou, rode `make openapi`.
7. Marque `[x]` na tarefa e faça commit `tipo(módulo): descrição ($1/$2)` com trailer `Co-Authored-By`.
8. Não implemente nada além da tarefa. Se descobrir algo faltando na spec, registre em "Perguntas em aberto".
