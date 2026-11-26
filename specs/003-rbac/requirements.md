# 003 · RBAC com escopo · Requisitos

- Status: Aprovado (Rafael, 07/11/2026). Emenda de 09/11/2026 (escopo de `dashboard:read` por papel) aprovada (Vinicius, 09/11/2026); ver § Emenda
- Dono humano: Vinicius (ViniciusVbm), desde 09/11/2026; antes: Rafael, autor desta spec e responsável pelas aprovações de requisitos, design e tarefas de 07/11/2026, que continuam válidas e com o nome dele (`steering/sdd-workflow.md` § Dono da spec)
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
- (003/T1) `group_role_mappings.group_id` aponta para `groups`, que só nasce na 004/T1. Quem põe a FK? (padrão adotado: a 0003 cria a coluna sem FK, e a migração da 004/T1 acrescenta a FK)
- (003/T1) `role_assignments.scope_id` e `group_role_mappings.scope_id` guardam id de distrito ou de área (smallint) ou de unidade (uuid). Qual tipo e como garantir que o escopo existe? (padrão adotado: `varchar(36)` sem FK, nulo só no escopo global, por CHECK; a existência é conferida na atribuição, R2.2)
- (003/T3) O passo 2 do design "limita cada escopo ao `max_scope`". Lido como teto, um `COORD_TECNICO` atribuído a uma área leria só as unidades da área, contra a matriz (`unidade:read` = G, e a nota do § 4 da arquitetura). Como conciliar? (padrão adotado: `max_scope` `global` é a letra G e vale em todo lugar, seja qual for o escopo da atribuição; nos demais níveis vale o escopo da atribuição se estiver contido no máximo, ou seja, o mesmo nível ou uma unidade sob `area` ou `distrito`; atribuição mais ampla que o máximo ou do outro eixo, área × distrito, não dá aquela permissão. Consequência para a T7: num papel só com G (`GESTOR_DADOS`, `DIRETORIA`, `AUDITOR`, `ADMIN_TI`), o escopo da atribuição não restringe nada, então R2.1 deve exigir `global` nesses papéis)
- (003/T3) Quem incrementa `users.authz_version`? (padrão adotado: o caso de uso que altera atribuições, T7 e T8, chama `RepositorioDePermissoes.invalidar(usuario_id)` na mesma transação; uma alteração feita direto no banco, sem incrementar, vale em até 30 s pelo TTL do cache)
- (003/T4) Recurso que não existe numa rota com `ResourceRef`: 403 ou 404? (padrão adotado: quem não tem a permissão em escopo nenhum recebe 403 sem o recurso ser procurado, e o 403 não revela se ele existe; quem tem a permissão em algum escopo recebe 404. Um id fora do formato do recurso conta como inexistente)
- (003/T4) O resolvedor da unidade (`ResourceRef("unidade")` → id, distrito, área técnica) precisa de `unit_types.technical_area_id`, que nasce na 0006 (006/T1). Quem o entrega? (padrão adotado: a T4 entrega o mecanismo, `ResourceRef` com a porta `ResolvedorDeAlvo` registrada por tipo em `app.state.resolvedores_de_alvo`, e também o resolvedor `unidade`, porque a 0006 entrou na integração durante a tarefa; ele lê `health_units` e `unit_types` em `access/infrastructure`, como a leitura de `users.authz_version`)
- (003/T4) O design pede `scope_filter(perm, model)`, mas a camada `api` não enxerga as tabelas (a `infrastructure` só é importada pela raiz de composição) e a `infrastructure` de outro módulo não importa a `application` nem a `api` do `access`. Como ficam a assinatura e o lugar? (padrão adotado: `scope_filter(escopo, model)` em `src/core/escopo.py`, que recebe o `EscopoLeitura` de `escopo_de_leitura(usuario, perm)` e um `model` com as colunas `unit_id`, `district_id` e `technical_area_id`, como as views da 011; ao lado, `parametros_de_escopo(escopo)` dá os parâmetros `:scope_*` do fragmento fixo do SQL escrito à mão)
- (003/T8) R3.1 e R3.2 dependem dos membros dos grupos, mas `groups` e `user_groups` só nascem na 004/T1. Como a T8 entrega sem eles? (padrão adotado: a porta `MembrosDeGrupo.membros_ativos(grupo_id)` dá os membros ativos; até a 004, a raiz de composição liga `SemMembrosDeGrupo`, que não dá membro nenhum, e a 004/T4 a troca pela leitura de `user_groups`. A entrada e a saída de grupos, R3.2, são o caso de uso `recalcular_derivadas_do_usuario(usuario_id, grupos)`, que quem espelha o diretório (004/T3, T5, T7) chama na mesma transação com todos os grupos atuais do usuário: cria a derivada de cada mapeamento que falta, remove a dos grupos que ele deixou e, sem mudança, não grava nada. O `grupo_id` do `POST` não é conferido, porque não há onde: a 004/T1 põe a FK. O teste troca a porta por um diretório em memória)
- (003/T8) O design não fixa o formato de `/admin/mapeamentos-grupo`. (padrão adotado, no formato de `/admin/atribuicoes` da T7: `POST` com `grupo_id`, `papel` (código), `escopo_tipo` e `escopo_id`, com as mesmas regras de escopo da atribuição, R2.1 e R2.2 (422 em `papel`, `escopo_tipo` ou `escopo_id`); o mesmo grupo, papel e escopo já mapeados, 409, conferido pela aplicação; responde 201 com `{id, grupo_id, papel, escopo_tipo, escopo_id, criado_por}`; `GET` devolve a lista, na ordem de criação; `DELETE /admin/mapeamentos-grupo/{id}` remove as derivadas e o mapeamento, 404 se não existe. Derivada sem `granted_by` nem `valid_until`, com `group_mapping_id`. Auditoria: `mapeamento.criado` e `mapeamento.removido`, `entity_type` `mapeamento_grupo`, metadados `mapeamento_id`, `grupo_id`, `papel`, `escopo_tipo`, `escopo_id` e `criado_por` ou `removido_por`; e cada derivada criada ou removida como `papel.atribuido` ou `papel.removido`, como na T7 (`entity_type` `usuario`), com `origem` `group` e `mapeamento_id` nos metadados no lugar de quem concedeu, que é o autor do evento. Cada usuário afetado tem `authz_version` incrementado)
- (003/T8) Quem mapeia um grupo de que é membro atribui papel a si mesmo. R2.5 vale aqui? (padrão adotado: sim, pelo mais restritivo de `steering/security.md`: 403 `acesso.negado` com o grupo como recurso. Um admin que entra depois num grupo já mapeado recebe a derivada pelo recálculo, porque não foi ele quem concedeu. A remoção de mapeamento não confere se quem remove é membro)

## Emenda (09/11/2026; aprovada, Vinicius, 09/11/2026)
- **Escopo de `dashboard:read` por papel (011/T22):** a matriz que a R1.1 adota (`docs/architecture/arquitetura-conceitual.md` § 4) passa a dar `dashboard:read` com escopo máximo `A` ao `COORD_TECNICO`, `D` ao `TECNICO_DISTRITAL` e `U` ao `GESTOR_UNIDADE`. `GESTOR_DADOS` e `DIRETORIA` continuam `G`. Menor privilégio: o painel de cada perfil fica no próprio escopo, como pede a história da 011/R2.
- Implementação já existente, sem mudança de código nesta emenda: a 0003 continua semeando a matriz original e a revisão `0011_09` aplica o ajuste (`migrations/sql/0011_09/17_dashboard_read_escopo_por_papel.sql`). O teste da R1.1 confere a matriz com o delta (`tests/integration/access/test_seed_matriz.py`, `AJUSTES_DA_0011_09`); o efeito no painel é provado por `tests/integration/dashboard/test_painel.py::test_escopo_do_tecnico_distrital_reduz_os_numeros`.
