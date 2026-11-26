# Rodando as frentes com agentes

- Para quem: os três integrantes que vão rodar, cada um na sua máquina, um agente de código (Claude Code) numa frente, ao mesmo tempo.
- Leia antes: o [README desta pasta](README.md) (regras, integração, pontos de encontro) e o guia da sua frente.

## O modelo
| Quem | Frente | Primeira tarefa |
|---|---|---|
| Pessoa 1 | [A · Diretório LDAP](frente-a-diretorio-ldap.md) | porte da 003/T8 |
| Pessoa 2 | [B · OIDC e laboratório](frente-b-oidc-laboratorio.md) | 004/T8 (conferência do `iss` do Keycloak) |
| Pessoa 3 | [C · Relatórios](frente-c-relatorios.md) | 005/T10 (conferência do SeaweedFS) |

- **Uma tarefa por sessão.** A pessoa roda `/frente a` (ou `b`, `c`); o agente pega a próxima tarefa livre da frente, faz com teste primeiro, roda o `make check`, faz o commit, revisa o próprio diff e **para**.
- **A pessoa revisa e integra.** Ela lê o diff e responde "integre", e o agente rebaseia, roda o `make check` de novo e envia ao `feat/004-005`. Depois, `/clear` e `/frente a` de novo.
- **Ninguém precisa avisar para destravar.** Todo commit integrado cita a tarefa (`(004/T1)`), então o agente confere sozinho no `git log` se o bloqueio de outra frente já entrou. O aviso no canal do grupo continua, para todo mundo saber o andamento.

## A skill `/frente`
Tudo passa por uma skill do repositório, [`.claude/skills/frente/`](../../.claude/skills/frente/SKILL.md): `/frente a` (ou `b`, `c`).

**Na primeira vez (uns 20 minutos),** num terminal comum do sistema, não num editor em sandbox como o VS Code em Flatpak, que esconde o Docker e o `uv`. Sem clone, antes: `git clone git@github.com:rafareloM/sgs-api.git ~/sgs-api`.

```bash
cd ~/sgs-api && git fetch origin && git switch feat/004-005 && claude
```

Dentro do Claude Code, `/frente a`. A skill vê que a sessão ainda não está no *worktree* da frente e prepara a máquina: confere o Docker, o `uv` e o SELinux, cria o *worktree* `../sgs-frente-a`, gera `secrets/` e `docker/.env`, instala as permissões e roda o `make check`. Antes de qualquer `sudo`, ela pede aprovação. No fim, manda abrir o `claude` no *worktree*.

**A cada tarefa,** no *worktree*: `claude` e `/frente a`. A skill atualiza o ramo, escolhe a primeira tarefa livre da "Ordem" do guia (conferindo os bloqueios no `git log`), implementa com `/spec-implementar`, revisa o diff (skill `code-review` e checklist de `steering/security.md`), mostra o diff com os achados e para. Depois da sua revisão (seção abaixo), responda "integre": ela rebaseia, roda o `make check`, envia ao `feat/004-005` e devolve o aviso para o canal. Então `/clear` e `/frente a` de novo.

**Permissões no *worktree*** (`.claude/settings.local.json`, copiado de [claude-settings.exemplo.json](claude-settings.exemplo.json) na preparação e fora do Git):
- **Liberado sem pergunta:** `uv run`, `make check`, `make openapi`, `make migrate`, leitura e commits no git, `git push origin HEAD:feat/004-005`, `docker compose` dos arquivos do projeto, edição de `src/`, `tests/`, `migrations/`, `specs/`, `docs/`, `contracts/`, `docker/` e `frontend/app/`.
- **Proibido:** push na `main`, push forçado, `--no-verify`, edição de `.claude/` e leitura de `secrets/`.
- **O resto pergunta.**

## O que revisar no diff (5 minutos por tarefa)
- O teste de "Pronto quando" existe, cita o critério na docstring e testa o comportamento, não a implementação.
- Rota nova tem `require(...)` ou está em `PUBLICAS`, e tem testes 401, 403 e 422.
- Nenhum segredo, token, senha ou URL pré-assinada em log, exceção ou resposta.
- Auditoria na mesma transação.
- Nada fora da tarefa e nada fora da lista de arquivos da frente.
- O `contracts/openapi.yaml` saiu do `make openapi`, não de edição à mão.

## Para andar rápido sem quebrar nada
- **Sessões curtas.** Uma tarefa por sessão, com `/clear` entre elas: a tarefa e o design bastam, e o contexto limpo erra menos.
- **Testes durante o trabalho:** o agente roda só a pasta da tarefa (`uv run pytest tests/unit/identity -q`); o `make check` completo fica para antes do commit e antes do push. Os testes `slow` (`tests/e2e/`) só nas tarefas de ambiente e de ponta a ponta.
- **Bloqueado?** A skill já escolhe a próxima tarefa livre da ordem. Se nenhuma estiver livre, aproveite para revisar o diff integrado de outra frente.
- **Conferências de risco** (primeira tarefa de B e de C, T11 de A): a pessoa acompanha. Se falharem, o plano muda, e quem decide são os donos (Rafael e Vinicius).
- **Duas frentes na mesma máquina?** Use subnets e portas diferentes no `docker/.env` de cada *worktree* (README § Ramos e *worktrees*). Em máquinas separadas, os valores padrão servem.
