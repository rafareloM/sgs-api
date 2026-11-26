# ADR-0007: Dependências complementares da stack (Uvicorn, limits, pytest-cov)

- Status: Aceito (Rafael, 03/10/2026); emenda de 09/11/2026 aceita (Vinicius, 09/11/2026); emenda 2 de 24/11/2026 aceita (Rafael, rafareloM, dono das specs 004 e 005, com o G2 da 004; registro do agente por autorização expressa na sessão de trabalho); emenda 3 de 24/11/2026 aceita (Rafael, na 004/T0; registro do agente por autorização expressa)
- Data: 2026-10-03
- Requisitos relacionados: RS-09, RNF-06; specs 001 (R1.1, R7.1) e 002 (R1.5)

## Contexto
A tabela de `steering/tech.md` fixa a stack, mas três peças necessárias não estavam nela:
- um servidor ASGI para rodar a API no container (a pesquisa da stack, §1, já citava o Uvicorn);
- o rate limit de `POST /auth/login` (002/R1.5), que o design da 002 atribui ao slowapi;
- a cobertura de testes no CI, que o workflow já chamava com `pytest --cov`.

## Decisão
Adicionar à stack, com a mesma regra de versão das demais (série fixa, `uv.lock` com a versão exata):

| Item | Versão | Uso |
|---|---|---|
| Uvicorn | 0.54.x | Servidor ASGI (`uvicorn --factory src.main:create_app`) |
| slowapi | 0.1.x | Rate limit por IP no login; entra no `pyproject.toml` na 002/T7 |
| pytest-cov | 7.x | Relatório de cobertura no CI (só desenvolvimento) |

## Consequências
- `steering/tech.md` passa a listar as três.
- O Uvicorn entra sem o extra `standard` (sem uvloop, httptools e watchfiles) para manter a imagem enxuta; desempenho do servidor não é gargalo no MVP.
- O slowapi tem manutenção modesta (0.1.10, junho de 2026). Se perder suporte, o limite vira uma dependência FastAPI própria sem mudar as rotas.

## Alternativas consideradas
- `fastapi[standard]`: traz o Uvicorn junto com pacotes que não usamos (CLI, templates, formulários, validação de e-mail).
- Hypercorn ou Granian: menos difundidos no ecossistema FastAPI.
- Rate limit próprio em memória: menos código externo, mas reimplementa janela de tempo e chave por IP que o slowapi já resolve e testa.
- CI sem cobertura: perde a métrica usada na revisão dos PRs.

## Emenda (09/11/2026, consolidação final; aceita, Vinicius, 09/11/2026, item V6 de `docs/relatorios/REGULARIZACAO_GOVERNANCA_SPECS.md`)
- **slowapi → limits.** O slowapi aplica o limite por decorador, com um `Limiter` global criado na importação do módulo, o que não combina com a raiz de composição do projeto (um app por `create_app`, um app por teste). A 002/T7 usa direto a biblioteca `limits` (o motor do slowapi), num limitador por app em `src/core/limite.py`, como este ADR já previa ("o limite vira uma dependência FastAPI própria"). As rotas não mudam.
- **pwdlib[argon2] e pyotp** entram no `pyproject.toml` na 002/T3 e T5, como a `steering/tech.md` prevê.
- Com o aceite, `steering/tech.md` passou a listar `limits 5.8.x` no lugar de `slowapi 0.1.x`. O título passou a citar `limits` (antes: "Uvicorn, slowapi, pytest-cov"). O texto original deste ADR, que escolheu o slowapi, fica como registro da decisão de 03/10/2026.

## Emenda 2 (24/11/2026; aceita pelo Rafael em 24/11/2026, com o G2 da 004)
- **httpx em execução.** O login OIDC da spec 004 usa o cliente assíncrono da Authlib (`authlib.integrations.httpx_client`), que precisa do `httpx`. Hoje o `httpx` está só no grupo `dev` (cliente dos testes). A emenda o passa às dependências de execução, na série já travada (0.28.x). Ele entra no `pyproject.toml` na tarefa da 004 que implementa o adaptador OIDC.
- **Por que não outra coisa.** O cliente `requests` da Authlib é bloqueante e também fica fora da stack. Montar a troca do código com `urllib` reimplementa timeout, TLS e formulário. Detalhes no design da 004, D004-4.
- Com o aceite, `steering/tech.md` passou a listar `httpx 0.28.x` na tabela da stack, com a nota "cliente HTTP da Authlib (004)".

## Emenda 3 (24/11/2026; aceita pelo Rafael em 24/11/2026, na 004/T0)
- **Authlib 1.8.x → 1.9.x.** Na T0 das specs 004 e 005, o `pip-audit` do CI acusou oito avisos de segurança na Authlib 1.8.0, corrigidos na 1.9.0 e na 1.9.1: PYSEC-2026-4355 a PYSEC-2026-4360, CVE-2026-96760 e CVE-2026-116672.
- **Alcance.** A maioria atinge partes que a 004 não usa: o servidor OAuth e a JOSE da Authlib, já que o `id_token` é conferido com o PyJWT (design da 004, D004-3). Mesmo assim, o CI recusa qualquer dependência com aviso conhecido.
- **Decisão.** A série passa a 1.9.x, travada na 1.9.10 no `uv.lock`. A parte da Authlib que a 004 usa (cliente OAuth assíncrono, PKCE) não muda, e o design da 004 também não.
- `steering/tech.md` passou a listar `Authlib 1.9.x`.
