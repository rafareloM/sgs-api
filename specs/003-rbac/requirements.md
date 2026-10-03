# 003 · RBAC com escopo · Requisitos

- Status: Rascunho
- Rastreia: RS-02, RS-05, critérios 6.1 "dois perfis veem e alteram dados diferentes" e "gestor de unidade não edita outra unidade"

## Contexto
Requisitos obrigatórios: "analisar o contexto para elencar papéis e recursos" e "implementar uma arquitetura de gestão de acesso baseada em RBAC". Papéis, recursos e a matriz estão em `docs/architecture/arquitetura-conceitual.md` §2 a §4.

## Fora do escopo
- Workflow de proposta e validação de alterações (RF-04): permissões criadas, fluxo não implementado.
- Interface de administração (front-end).

## Histórias e critérios

### R1. Catálogo de papéis e permissões
- R1.1 O sistema DEVE criar, por migração, os papéis `ADMIN_TI`, `GESTOR_DADOS`, `COORD_TECNICO`, `TECNICO_DISTRITAL`, `GESTOR_UNIDADE`, `DIRETORIA` e `AUDITOR` e as permissões da matriz.
- R1.2 O sistema DEVE associar cada permissão de um papel a um escopo máximo (`global`, `area`, `distrito`, `unidade`).
- R1.3 O sistema NÃO DEVE permitir apagar papéis de sistema.

### R2. Atribuições
- R2.1 QUANDO um usuário com `papel:assign` atribui um papel a um usuário, o sistema DEVE exigir o escopo compatível com o papel (ex.: `GESTOR_UNIDADE` exige `unidade`).
- R2.2 SE o escopo informado não existir ou for maior que o permitido para o papel, ENTÃO o sistema DEVE responder 422.
- R2.3 O sistema DEVE permitir atribuição com data de expiração opcional e ignorar atribuições expiradas.
- R2.4 O sistema DEVE auditar `papel.atribuido` e `papel.removido` com quem concedeu.
- R2.5 SE o usuário tentar atribuir papel a si mesmo, ENTÃO o sistema DEVE responder 403 (segregação de funções).

### R3. Mapeamento de grupos para papéis
- R3.1 QUANDO o Admin TI cria um mapeamento grupo→papel+escopo, o sistema DEVE criar atribuições de origem `group` para todos os membros ativos do grupo.
- R3.2 QUANDO um usuário entra ou sai de um grupo mapeado, o sistema DEVE adicionar ou remover as atribuições derivadas.
- R3.3 O sistema NÃO DEVE alterar atribuições de origem `direct` ao recalcular atribuições de grupo.

### R4. Verificação de acesso
- R4.1 O sistema DEVE negar por padrão: toda rota em `/api/v1` que não seja pública DEVE declarar uma permissão.
- R4.2 QUANDO o usuário não tem a permissão exigida em nenhum escopo, o sistema DEVE responder 403.
- R4.3 QUANDO a permissão depende de um recurso (ex.: unidade 42), o sistema DEVE verificar se o recurso está dentro de algum escopo do usuário para aquela permissão.
- R4.4 QUANDO o usuário lista um recurso, o sistema DEVE retornar apenas itens dentro do seu escopo de leitura.
- R4.5 QUANDO um papel é removido, o sistema DEVE refletir a mudança na próxima requisição (sem esperar o token expirar).
- R4.6 SE o acesso for negado, ENTÃO o sistema DEVE auditar `acesso.negado` com a permissão e o recurso.

### R5. Perfil do usuário logado
- R5.1 QUANDO o usuário chama `GET /me`, o sistema DEVE devolver dados básicos, papéis com escopos e a lista de permissões efetivas, para o front montar a tela inicial coerente com o perfil.

## Perguntas em aberto
- `TECNICO_DISTRITAL` pode criar unidade no seu distrito ou apenas atualizar? (padrão adotado: apenas atualizar)
- Leitura de unidades deve ser global para todos os papéis? (padrão adotado: sim, dados públicos/internos)
