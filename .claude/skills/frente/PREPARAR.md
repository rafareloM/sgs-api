# Preparar a máquina para uma frente

Lido pela skill `/frente` quando a sessão ainda não está no *worktree* da frente. Nos comandos abaixo, troque `a` pela letra da frente.

Nesta preparação, commits, pushes e arquivos versionados ficam como estão, e o conteúdo de `secrets/` fica fora da tela. Antes de `sudo`, de instalar programa no sistema ou de mudar algo fora do projeto (exceto `~/.testcontainers.properties`), mostre o comando e espere a pessoa aprovar.

1. **Sandbox.** Se existir `/.flatpak-info` ou a variável `$container`, a sessão está num sandbox (por exemplo, o VS Code em Flatpak) que esconde o Docker e o `uv`: peça para abrir o `claude` num terminal comum do sistema e pare. Numa AppVM do Qubes (`qubesdb-read /qubes-vm-type` responde `AppVM`), avise que o que for instalado some quando a qube reinicia e que o Docker vai no template.
2. **Ferramentas.** Mostre as versões: Docker 26 ou mais novo com o plugin Compose (`docker compose version`), `uv` (procure também em `~/.local/bin`), GNU Make, git e acesso SSH ao GitHub (`ssh -T git@github.com`). O `docker info` tem de responder sem `sudo`; no Linux, isso é `sudo usermod -aG docker $USER` e um login novo. Para o que faltar, diga como instalar naquele sistema.
3. **SELinux.** Se `docker info --format '{{.SecurityOptions}}'` mencionar `selinux` (Fedora, por exemplo), garanta a linha `ryuk.container.privileged=true` em `~/.testcontainers.properties`, mantendo as outras linhas do arquivo. Sem ela, o SELinux impede o Ryuk do testcontainers de falar com o Docker, e todo teste de integração dá erro com `Port mapping ... port 8080 is not available`.
4. **Worktree.** No clone, crie o *worktree* a partir do `feat/004-005`. Se ele ou o ramo já existirem, reaproveite.

   ```bash
   git fetch origin
   git worktree add ../sgs-frente-a -b frente/a origin/feat/004-005
   ```

   Os passos seguintes rodam dentro de `../sgs-frente-a`.
5. **Projeto.** Rode o que ainda não existir:

   ```bash
   uv sync
   uv run pre-commit install
   mkdir -p secrets
   uv run python -m src.tools.jwt_keys --output secrets/jwt-keys.json
   uv run python -m src.tools.crypto_keys --output secrets/crypto-keys.json
   printf 'SGS_BORDA_SUBNET=10.231.1.0/28\nSGS_BORDA_PROXY_IP=10.231.1.14\n' > docker/.env
   mkdir -p .claude && cp docs/implementacao/claude-settings.exemplo.json .claude/settings.local.json
   ```

   Se `git worktree list` mostrar o *worktree* de outra frente nesta máquina, o `docker/.env` precisa de outra subnet e de outras portas: siga `docs/implementacao/README.md` § Ramos e *worktrees* e combine os valores com a pessoa.
6. **`make check`** no *worktree* (precisa do Docker; uns 3 minutos). Pronto quando: verde. Falha de ambiente (Docker, permissões, SELinux, `docker/.env`, portas ocupadas) se corrige aqui. Falha de código ou de teste vai para os donos (Rafael e Vinicius): mostre o resumo e pare.
7. **Resumo:** versões, caminho do *worktree*, ramo, hash do `origin/feat/004-005` e resultado do `make check`. Próximo passo da pessoa: fechar esta sessão, `cd ../sgs-frente-a && claude` e `/frente a`.
