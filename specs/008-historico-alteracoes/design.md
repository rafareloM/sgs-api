# 008 · Histórico de alterações · Design

- Status: Rascunho

## Consulta
- `audit/application/consultar.py` monta a query sobre `audit_log` com índices `(entity_type, entity_id, occurred_at DESC)` e `(action, occurred_at DESC)`.
- Rótulos legíveis: dicionário `ROTULOS_CAMPOS` no módulo `registry` (ex.: `district_id` → "Distrito sanitário"), e os ids de referência são traduzidos para nomes na resposta.
- Escopo: o histórico de uma unidade usa o mesmo `require("auditoria:read", Unidade(id))` da spec 003.
- Fuso: armazenado em UTC; serializado em `America/Recife`.

## Verificação da cadeia
Recalcula em lotes de 1.000 eventos em ordem de `id`, comparando `hash` com `sha256(prev_hash + canon(evento))`. Retorna o primeiro `id` divergente. Operação só leitura.

## Partições
Migração `0008_auditoria_particoes` converte `audit_log` em particionada por mês e cria partições dos próximos 12 meses; tarefa de manutenção cria novas mensalmente (comando `sgs-admin audit-partitions`).

## Rotas
| Método e rota | Permissão | Requisitos |
|---|---|---|
| `GET /api/v1/unidades/{id}/historico` | `auditoria:read` (escopo da unidade) | R1 |
| `GET /api/v1/auditoria/eventos` · `/{id}` | `auditoria:read` global; `auth.*` exige `auditoria:read_acessos` | R2, R3.2 |
| `POST /api/v1/auditoria/verificar` | `auditoria:read` global | R3.1 |

## Estratégia de testes
- Integração: alteração via spec 006 aparece no histórico com autor, papel, data e campos (teste de aceitação 6.1); filtros; 403 fora do escopo; eventos `auth.*` ocultos sem permissão.
- Integridade: adulterar um registro com superusuário no teste (desabilitando o trigger) e verificar que a cadeia acusa o ponto exato.
