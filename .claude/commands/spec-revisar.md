---
description: Revisa o diff atual contra a spec e o checklist de segurança
argument-hint: <NNN-nome>
---
Revise o diff da branch atual em relação a `main`.

1. Para cada tarefa marcada `[x]` em `specs/$1/tasks.md`, confirme que o teste citado existe e cobre os requisitos.
2. Aplique o checklist de `steering/security.md` item a item e diga o resultado de cada um.
3. Procure divergências entre código e `design.md`; aponte qual dos dois deve mudar.
4. Verifique rotas sem `require`, listagens sem `scope_filter`, alterações sem auditoria e segredos em log.
5. Responda com: bloqueantes, sugestões e o que está bom. Não altere arquivos.
