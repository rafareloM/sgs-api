# ADR-0007: Dependências complementares da stack (Uvicorn, slowapi, pytest-cov)

- Status: Aceito (Leonardo, 03/10/2026)
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
| Uvicorn | 0.54.x | Servidor ASGI (`uvicorn --factory sgs_api.main:create_app`) |
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
