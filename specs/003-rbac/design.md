# 003 · RBAC com escopo · Design

- Status: Rascunho

## Modelo
Migração `0003_access`: `roles`, `permissions`, `role_permissions(max_scope)`, `role_assignments`, `group_role_mappings`, mais tabelas de referência necessárias para escopo (`districts`, `technical_areas`) e um stub de `health_units` (id, district_id, unit_type_id) que a spec 006 completa.

## Resolução de permissões
```
PermissoesEfetivas = dict[permission_code, list[Escopo]]
Escopo = Global | Area(id) | Distrito(id) | Unidade(id)
```
1. Carrega atribuições ativas do usuário (diretas + derivadas de grupo, não expiradas).
2. Junta com `role_permissions` e limita cada escopo ao `max_scope` da permissão no papel.
3. Cache em memória por `user_id` com TTL de 30 s e invalidação ao alterar atribuições (versão por usuário em `users.authz_version`).

## Verificação
- Dependência `require(perm: str, resource: ResourceRef | None = None)`.
- `ResourceRef` resolve o recurso para seus atributos de escopo: unidade → (`unit_id`, `district_id`, `area_id`).
- Regra: autorizado se existir algum escopo `Global`, ou `Area` igual à área da unidade, ou `Distrito` igual ao distrito, ou `Unidade` igual ao id.
- Listagens: `scope_filter(perm, model)` devolve uma expressão SQLAlchemy (`or_(...)`) aplicada na query.
- Função pura `pode(perms, perm, alvo) -> bool` no `domain`, testável sem banco.

## Deny by default
Teste `tests/architecture/test_rotas_protegidas.py` percorre `app.routes` e falha se uma rota de `/api/v1` não tiver a dependência `require` nem estiver na lista explícita de rotas públicas.

## Rotas
| Método e rota | Permissão | Requisitos |
|---|---|---|
| `GET /api/v1/me` | autenticado | R5.1 |
| `GET /api/v1/admin/papeis` | `papel:assign` | R1 |
| `GET/POST/DELETE /api/v1/admin/atribuicoes` | `papel:assign` | R2 |
| `GET/POST/DELETE /api/v1/admin/mapeamentos-grupo` | `papel:assign` | R3 |
| `GET/POST/PATCH /api/v1/admin/usuarios` | `usuario:manage` | R2 |

## Segurança
- 403 em vez de 404 para recursos fora do escopo (decisão por clareza na demonstração; revisar se houver risco de enumeração).
- Admin TI não recebe permissões de cadastro (segregação).

## Estratégia de testes
- Unidade: `pode()` com tabela de casos gerada a partir da matriz (um caso por célula).
- Propriedade (hypothesis): remover uma atribuição nunca aumenta permissões.
- Integração: gestor da unidade A recebe 403 ao alterar unidade B; técnico do DS III lista só unidades do DS III quando a leitura for restrita; remoção de papel vale na próxima chamada.
