---
name: frente
description: Prepara a máquina ou roda a próxima tarefa de uma frente (a, b ou c) das specs 004 e 005
argument-hint: <a|b|c>
disable-model-invocation: true
---
Frente pedida: `$ARGUMENTS`.

| Frente | Guia |
|---|---|
| a | `docs/implementacao/frente-a-diretorio-ldap.md` |
| b | `docs/implementacao/frente-b-oidc-laboratorio.md` |
| c | `docs/implementacao/frente-c-relatorios.md` |

Sem uma dessas letras, pergunte a frente antes de seguir.

## Qual sessão é esta
- Ramo atual (`git branch --show-current`) `frente/<letra>`, com `docker/.env` presente: **sessão de tarefa**, abaixo.
- Ramo `frente/<outra letra>`: este *worktree* é de outra frente. Diga isso e pare.
- Qualquer outro caso: **preparação**. Leia [PREPARAR.md](PREPARAR.md), nesta pasta, e siga.

## Sessão de tarefa
Uma tarefa por sessão. Leia `docs/implementacao/README.md` e o guia da frente.

1. **Atualize:** `git fetch origin && git rebase origin/feat/004-005`. Se `git log origin/feat/004-005..HEAD` mostrar commits, há uma tarefa ainda não integrada: mostre-a e pergunte se a pessoa quer integrar (passo 7) antes de começar outra.
2. **Escolha a tarefa:** a primeira da linha "Ordem" do guia que ainda está `[ ]` no `tasks.md` da spec dela e cujos bloqueios ("Bloqueada por") já estão integrados. Para cada bloqueio `NNN/Tn`:

   ```bash
   git log origin/feat/004-005 --oneline -E --grep='NNN/Tn[,)]'
   ```

   Pronto quando: há uma tarefa livre, ou a lista completa dos bloqueios que faltam. Sem tarefa livre, mostre essa lista e pare.
3. **Implemente só essa tarefa** seguindo `.claude/commands/spec-implementar.md`. Ao marcar `[x]`, acrescente logo abaixo da tarefa a linha de prova:

   ```text
     - Concluída em DD/MM/AAAA (`make check` verde). Prova: `tests/caminho/test_x.py::test_y`
   ```

4. **Chame a pessoa e pare** se a tarefa pedir mudança de requisito, de design, de dependência (`pyproject.toml`, `uv.lock`) ou de arquivo fora da lista da frente, ou se cair em `docs/implementacao/README.md` § Quando parar e chamar os donos.
5. **Revise o próprio diff** antes de mostrar. Rode a skill `code-review` sobre `origin/feat/004-005..HEAD` e confira o checklist de `steering/security.md` item a item. O que for defeito desta tarefa, corrija com teste, no mesmo commit (`git commit --amend`), e rode o `make check` de novo. O que pedir decisão ou for de outra tarefa vai para o resumo.

   Pronto quando: cada achado está corrigido ou listado para a pessoa.
6. **Mostre o resumo:** `git show --stat HEAD`, os testes que provam a tarefa, o resultado do `make check` e os achados da revisão, corrigidos e pendentes. Espere a pessoa revisar e responder "integre".
7. **Integre** depois do "integre":

   ```bash
   git fetch origin && git rebase origin/feat/004-005 && make check && git push origin HEAD:feat/004-005
   ```

   Push recusado porque outra frente integrou antes: repita a linha. Conflito no `tasks.md` costuma ser só de marcação: as duas marcações ficam. No fim, dê à pessoa o aviso para o canal do grupo, `Integrada: NNN/Tn (<hash>)`, e o próximo passo: `/clear` e `/frente <letra>`.
