# 007 · Validação de dados · Design

- Status: Rascunho

## Camadas de validação
1. **Formato (Pydantic, camada `api`)**: tipos, tamanhos, normalização (`BeforeValidator` remove máscara) e formatos fixos de R1.3. Erros viram 422 via handler da spec 001.
2. **Domínio (`registry/domain/validacao.py`)**: regras de coerência (R1.4, R1.5) como funções puras `Regra = Callable[[Contexto], list[Violacao]]`, registradas em uma lista.
3. **Configuráveis (`validation_rules`)**: interpretador simples para `obrigatorio`, `regex` (com `re.fullmatch` e limite de tamanho para evitar ReDoS), `lista`, `intervalo`.

`Validador.validar(entidade, dados, contexto) -> ResultadoValidacao(bloqueantes, alertas)`. O caso de uso de gravação (spec 006) chama o validador antes de persistir; se houver bloqueantes, levanta `DomainValidationError(erros)` → 422 com o mesmo formato de erro do Pydantic (R1.2).

## Modelo
Migração `0007_validacao`: `validation_rules` (ver modelo de dados) e `unit_pending_issues (unit_id, rule_id, field, message, detected_at)`.

## Rotas
| Método e rota | Permissão | Requisitos |
|---|---|---|
| `GET/POST/PATCH /api/v1/validacao/regras` | `regra_validacao:manage` | R2.1–R2.4 |
| `POST /api/v1/validacao/simular` | `unidade:update` (qualquer escopo) | R2.5 |
| `POST /api/v1/validacao/revalidar` | `regra_validacao:manage` | R3.3 |
| `GET /api/v1/unidades/{id}/pendencias` | `unidade:read` | R3.2 |

## Mensagens
Catálogo único `registry/domain/mensagens.py` (ex.: `"CEP deve ter 8 dígitos e estar em Recife (50000-000 a 52999-999)."`), reutilizado pelos schemas e regras, para o front exibir sem tradução.

## Segurança
Regex configurável é dado vindo de usuário: limitada a 200 caracteres, compilada na criação (R2.3) e recusada se tiver quantificadores aninhados como `(a+)+` (heurística contra ReDoS). Risco residual registrado; se aparecer problema, avaliar a biblioteca `google-re2` via ADR.

## Estratégia de testes
- Unidade: cada regra fixa com casos válidos/inválidos (hypothesis para CEP e telefone); interpretador de regras configuráveis; regra CAPS × Farmácia da Família.
- Integração: 422 lista todos os erros e nada é gravado (contagem de linhas e de auditoria iguais antes/depois); alerta grava e cria pendência; revalidação recalcula.
