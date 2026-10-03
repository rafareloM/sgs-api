# Steering · Testes

## Pirâmide
| Nível | Pasta | Ferramentas | Roda no `make check` |
|---|---|---|---|
| Unidade | `tests/unit/` | pytest, hypothesis, ldap3 MOCK_SYNC | sim |
| Integração | `tests/integration/` | pytest-asyncio, httpx `AsyncClient`, testcontainers Postgres, moto | sim |
| Arquitetura | `tests/architecture/` | pytest, import-linter | sim |
| Contrato | `tests/contract/` | schemathesis | no CI |
| Ponta a ponta | `tests/e2e/` (`@pytest.mark.slow`) | compose com slapd, Keycloak, SeaweedFS | no CI noturno ou manual |

## Regras
- Nome do teste descreve o comportamento em português: `test_gestor_unidade_nao_edita_outra_unidade`.
- Todo critério `Rx.y` de uma spec tem pelo menos um teste que o cita na docstring (`"""004/R1.7"""`).
- Testes de segurança negativos são obrigatórios para rotas novas (401, 403, 422).
- Fábricas de dados com polyfactory ou funções `make_*`; nada de fixtures gigantes compartilhadas.
- Sem acesso à internet nos testes (S3 via moto, LDAP via mock, OIDC com JWKS gerado no teste).
- Usuários de seed por papel em `tests/fixtures/usuarios.py`, espelhando o LDIF de desenvolvimento.

## Critérios de aceitação da entrega final
Os testes dos critérios 6.1 da Entrega Final que dependem do backend formam a suíte `tests/acceptance/` e devem estar verdes antes de 21/11/2026.
