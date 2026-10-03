# 009 · Dashboard básico · Design

- Status: Rascunho

## Implementação
- Módulo `dashboard` só lê; consultas `GROUP BY` com `scope_filter` aplicado (spec 003). Sem tabela própria (Atividade 5 §4).
- Uma consulta por bloco, executadas em paralelo com `asyncio.gather` em sessões separadas.
- Cache em memória de 30 s por (usuário, filtros); invalidado por versão global incrementada a cada gravação no `registry`.

## Rota
| Método e rota | Permissão | Requisitos |
|---|---|---|
| `GET /api/v1/dashboard/resumo?distrito=&area=` | `dashboard:read` | R1 |

## Resposta (resumo)
```json
{
  "unidades": {"total": 0, "por_status": {}, "por_tipo": [], "por_area": [], "por_distrito": []},
  "qualidade": {"unidades_com_pendencias": 0, "total_pendencias": 0, "sem_cnes": 0, "servicos_fora_cnes": 0},
  "alteracoes": {"ultimos_7_dias": 0, "ultimos_30_dias": 0, "recentes": []},
  "gerado_em": "2026-10-03T10:00:00-03:00"
}
```

## Estratégia de testes
- Integração: cadastrar N unidades com a spec 006 e conferir cada número (teste de aceitação 6.1); escopo reduz os totais; filtros.
- Desempenho (`slow`): 1.000 unidades, p95 < 1 s.
