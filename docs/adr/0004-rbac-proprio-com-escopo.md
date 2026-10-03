# ADR-0004: RBAC próprio com escopo

- Status: Proposto
- Data: 2026-10-03
- Requisitos relacionados: RS-02, critério "gestor de unidade não edita outra unidade"

## Contexto
O requisito obrigatório é implementar gestão de acesso baseada em RBAC. A Entrega Final exige que dois perfis vejam e alterem conjuntos diferentes de dados, e o cliente descreveu níveis distrital e central.

## Decisão
Tabelas próprias de papéis, permissões (`recurso:acao`) e atribuições. Cada atribuição tem escopo (`global`, `area`, `distrito`, `unidade`). Papéis podem vir de atribuição direta ou de mapeamento grupo→papel (grupos do LDAP/OIDC). Autorização é uma dependência FastAPI declarada em cada rota, com deny by default verificado por teste.

## Consequências
- O modelo é visível no banco e explicável na apresentação.
- Escopo resolve a restrição por unidade e distrito sem ABAC completo.
- A matriz de permissões precisa de testes parametrizados para não regredir.

## Alternativas consideradas
- Casbin: motor genérico; esconde o modelo que a disciplina quer ver implementado.
- Scopes OAuth2 no token: estáticos até o token expirar e não expressam escopo por unidade.
