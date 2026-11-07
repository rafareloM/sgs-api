# 011 · Recursos de banco de dados · Requisitos

- Status: Aprovado (Rafael, 06/11/2026)
- Rastreia: requisitos da disciplina de Banco de Dados (Segunda Parte, entrega em 13/11/2026; Etapa 02 nas regras de integridade; Etapa 06 no CRUD de 4 tabelas); RF-01, RF-06, RF-08, RF-09, RS-02, RS-03, RS-05, RS-08; objetivo "protocolos criptográficos seguros" da disciplina de Criptografia (R10.3); ADR-0009
- Dono humano: Rafael
- Issue: #17

## Contexto
A disciplina de Banco de Dados cobra, até 13/11/2026, índices, consultas avançadas, views, funções, procedimentos e triggers com justificativa semântica, além dos dados seguros no SGBD e do SQL explícito no backend (ADR-0009). Esta spec reúne esses objetos num lugar só, para a rastreabilidade com a disciplina ficar clara. Os objetos servem ao domínio: qualidade do cadastro (pilar Validar), histórico (pilar Controlar) e indicadores (pilar Visualizar). As decisões que levaram a esta lista estão no grilling de 06/11/2026, guardado fora do git.

## Fora do escopo
- Interface (front-end): fica para spec própria, no repositório do front.
- CRUD das tabelas de cadastro: já está na 006 (unidades, equipamentos, serviços, referências). Esta spec só rastreia o "CRUD de ao menos 4 tabelas" para lá.
- Dashboard estatístico da Etapa 06 (séries, períodos, médias): fica na 009, emendada.
- Retenção e expurgo do log do banco.
- Particionamento da trilha de auditoria (`audit_log`).
- Recalcular pendências de validação e verificar a cadeia de hash da auditoria no banco: são regras que já ficam em Python (007 e 001/008).

## Histórias e critérios

### R1. Consultas rápidas por unidade
Como Auditor ou Gestor de Dados, quero que o histórico e o detalhe de uma unidade respondam rápido mesmo com a base crescendo, para conferir alterações sem esperar.

- R1.1 O sistema DEVE ter um índice que atenda à busca do histórico de uma unidade por tipo de entidade, identificador e data (mais recente primeiro).
- R1.2 O sistema DEVE ter um índice que atenda à busca dos serviços de uma unidade.
- R1.3 QUANDO o banco tem volume de demonstração (1.000 unidades, cerca de 3.000 serviços e a trilha correspondente), o plano de execução do histórico de uma unidade e dos serviços de uma unidade DEVE usar o índice correspondente.
- R1.4 Cada índice DEVE estar documentado com a consulta ou view que o usa e o plano de execução que comprova o uso.

### R2. Consultas de qualidade do cadastro
Como Gestor de Dados (ou Coordenador Técnico, Técnico Distrital, Gestor de Unidade e Diretoria, no próprio escopo), quero ver as lacunas do cadastro para saber onde agir.

- R2.1 QUANDO um usuário com `dashboard:read` consulta as unidades sem serviço, o sistema DEVE listar as unidades ativas que não têm nenhum serviço cadastrado (consulta com anti join).
- R2.2 QUANDO um usuário com `dashboard:read` consulta a conciliação unidade × equipamento, o sistema DEVE listar, numa mesma resposta, as unidades sem equipamento, os equipamentos sem unidade e os pares unidade-equipamento (consulta com full outer join).
- R2.3 QUANDO um usuário com `dashboard:read` consulta os distritos com mais unidades sem CNES, o sistema DEVE listar os distritos cujo percentual de unidades sem CNES é maior que o percentual da rede (consulta com subconsulta).
- R2.4 QUANDO um usuário com `dashboard:read` consulta as unidades com serviço fora do CNES, o sistema DEVE listar as unidades que ofertam ao menos um serviço que não consta no CNES (consulta com subconsulta).
- R2.5 O sistema DEVE aplicar o escopo de leitura do usuário (spec 003) em todas as consultas desta história. A "rede" de R2.3 DEVE ser o conjunto de unidades no escopo do usuário.
- R2.6 O sistema DEVE mostrar equipamentos sem unidade na conciliação apenas para usuários com escopo global.
- R2.7 As consultas DEVEM aceitar filtro por distrito e por tipo de unidade, quando a consulta tiver esses dados.
- R2.8 SE o usuário não tiver `dashboard:read`, ENTÃO o sistema DEVE responder 403.
- R2.9 SE um filtro tiver valor inválido (distrito ou tipo inexistente, formato errado), ENTÃO o sistema DEVE responder 422 sem executar a consulta.

### R3. Catálogo de consultas
Como integrante do grupo que apresenta o projeto (e como front-end), quero uma lista das consultas disponíveis com a explicação de cada uma, para mostrá-las com filtros e gráficos sem conhecer o SQL.

- R3.1 QUANDO um usuário com `dashboard:read` pede o catálogo, o sistema DEVE listar cada consulta e view exposta com título, justificativa semântica, parâmetros aceitos, colunas da resposta, permissão exigida e tipo de gráfico sugerido.
- R3.2 O catálogo DEVE listar apenas as consultas que o usuário tem permissão de executar.

### R4. Visões do cadastro e do histórico
Como Gestor de Dados, quero visões prontas do inventário da rede e do histórico de alterações, para que relatórios, dashboard e telas usem a mesma definição.

- R4.1 O sistema DEVE ter uma view de inventário com, por unidade: tipo, área técnica, distrito, status, situação cadastral (R5.3) e as quantidades de equipamentos, serviços e serviços fora do CNES. A view DEVE juntar pelo menos 3 tabelas.
- R4.2 A view de inventário NÃO DEVE expor o nome do gestor da unidade nem outro dado pessoal (LGPD, `steering/security.md`).
- R4.3 QUANDO um usuário com `dashboard:read` consulta o inventário, o sistema DEVE responder a partir da view, com o escopo de leitura do usuário e os filtros de R2.7.
- R4.4 O sistema DEVE ter uma view de histórico das unidades com data, autor, ação, unidade, distrito, tipo de unidade e a lista `{campo, de, para}`. A view DEVE juntar pelo menos 3 tabelas e incluir os eventos de equipamentos e serviços da unidade.
- R4.5 O histórico da unidade da spec 008 (R1) DEVE ser servido pela view de histórico.
- R4.6 As views DEVEM respeitar as permissões de quem consulta, não as de quem as criou.

### R5. Funções com regra de domínio
Como Gestor de Dados, quero que a normalização de nomes e a situação cadastral sejam calculadas no banco de um jeito só, para que busca, unicidade e indicadores concordem.

- R5.1 O sistema DEVE ter uma função que normaliza nomes: sem acento, em minúsculas, sem espaços nas pontas e com espaços repetidos reduzidos a um.
- R5.2 A unicidade por nome normalizado (006/R1.4) e a busca por texto livre (006/R2.2) DEVEM usar essa função. Para um mesmo texto, ela DEVE devolver sempre o mesmo resultado.
- R5.3 O sistema DEVE ter uma função, com estrutura condicional, que classifica a situação cadastral de uma unidade nesta ordem de precedência: `inativa` (status inativa), `com_pendencias` (tem pendência de validação), `sem_cnes` (sem código CNES), `regular` (nenhum dos anteriores). Ver Perguntas em aberto.

### R6. Procedimentos
Como Gestor de Dados, quero que a desativação de unidade e a manutenção do log do banco sejam operações do próprio banco, para que funcionem igual venha a chamada de onde vier.

- R6.1 O sistema DEVE ter um procedimento de atualização que desativa uma unidade e devolve o status anterior e a versão nova.
- R6.2 QUANDO um usuário com `unidade:deactivate` desativa uma unidade (006/R4), o sistema DEVE usar esse procedimento e registrar a auditoria na mesma transação.
- R6.3 SE a unidade não existir, ENTÃO o sistema DEVE responder 404 sem expor a mensagem do banco.
- R6.4 SE a unidade já estiver inativa, ENTÃO o sistema DEVE responder 200 sem alterar nada e sem gerar auditoria (mesma regra de 006/R3.6). Ver Perguntas em aberto.
- R6.5 O sistema DEVE ter um procedimento que usa cursor para garantir que existam as partições mensais do log do banco (R7), do mês atual até N meses à frente, sem apagar nenhuma partição.
- R6.6 SE já houver registros do log num mês ainda sem partição, ENTÃO o procedimento DEVE pular esse mês, emitir um aviso e seguir com os demais, sem perder nem mover registros.
- R6.7 QUANDO as migrações rodam, o sistema DEVE garantir partições do mês atual até 12 meses à frente.
- R6.8 O sistema DEVE oferecer um comando administrativo que executa o procedimento.
- R6.9 QUANDO um usuário com `auditoria:read` em escopo global consulta as partições do log do banco, o sistema DEVE listar cada partição com o intervalo e a quantidade de registros.

### R7. Log do banco
Como Auditor, quero que toda alteração nas tabelas do cadastro fique registrada pelo próprio banco, inclusive as feitas fora da API, para detectar mudanças que não passaram pela aplicação.

- R7.1 QUANDO uma unidade, equipamento ou serviço é incluído, alterado ou excluído, por qualquer meio, o banco DEVE gravar no log: data e hora, tabela, operação, identificador da linha, colunas alteradas (de/para), usuário de banco e se a alteração veio da API.
- R7.2 O log DEVE marcar como "fora da API" qualquer alteração feita por usuário de banco que não seja o da aplicação, inclusive superusuário.
- R7.3 O log NÃO DEVE guardar o valor de dado pessoal (nome do gestor da unidade); DEVE registrar só que o campo mudou, com o valor mascarado.
- R7.4 O log NÃO DEVE registrar alterações que mudem apenas a contagem de pendências, a versão ou a data de atualização.
- R7.5 Alterações em cascata (exclusão de equipamento, correção de código de referência) DEVEM aparecer no log como alterações das linhas afetadas.
- R7.6 O usuário de banco da aplicação DEVE poder apenas ler o log; NÃO DEVE conseguir incluir, alterar, apagar ou truncar registros diretamente.
- R7.7 QUANDO um usuário com `auditoria:read` em escopo global consulta o log do banco, o sistema DEVE listar os registros com filtros por período, tabela e "fora da API", paginados.
- R7.8 SE o usuário não tiver `auditoria:read` em escopo global, ENTÃO o sistema DEVE responder 403.

### R8. Versão da unidade em toda escrita
Como Gestor de Unidade, quero que qualquer mudança na unidade invalide a versão que eu tenho em mãos, para não sobrescrever uma alteração feita por outro meio.

- R8.1 QUANDO os dados de uma unidade mudam por qualquer meio (API, procedimento ou alteração direta no banco), o banco DEVE incrementar a versão da unidade e atualizar a data de atualização.
- R8.2 Mudança só na contagem de pendências NÃO DEVE alterar a versão.
- R8.3 SE um `PATCH` chegar com `If-Match` de uma versão anterior a uma alteração feita fora da API, ENTÃO o sistema DEVE responder 412 (006/R3.2).

### R9. Integridade referencial (Etapa 02)
Como Gestor de Dados, quero que o banco mantenha os vínculos coerentes quando um equipamento sai ou um código de referência é corrigido.

- R9.1 QUANDO um equipamento é removido, o banco DEVE manter os serviços que estavam nele, desligados do equipamento e ainda ligados à unidade (ON DELETE SET NULL).
- R9.2 QUANDO o Gestor de Dados corrige o código de um tipo de equipamento, o banco DEVE atualizar os equipamentos desse tipo (ON UPDATE CASCADE), e o sistema DEVE auditar a correção com a quantidade de equipamentos afetados.
- R9.3 O banco NÃO DEVE permitir apagar uma unidade que tenha equipamentos ou serviços vinculados.

### R10. Dados seguros no SGBD
Como Auditor (Segurança da Informação), quero que o banco aplique privilégio mínimo e conexão cifrada, para que um vazamento de credencial da aplicação tenha impacto limitado.

- R10.1 As funções, procedimentos e triggers DEVEM ser executáveis apenas pelos papéis que precisam deles; NÃO DEVEM ser executáveis por qualquer usuário do banco.
- R10.2 As funções e procedimentos que rodam com privilégio do dono DEVEM pertencer a um papel sem login e sem superusuário.
- R10.3 A conexão entre a API e o PostgreSQL DEVE usar TLS com verificação do certificado e do nome do servidor, também no ambiente local (compose).
- R10.4 SE alguém tentar conectar ao PostgreSQL pela rede sem TLS, ENTÃO o banco DEVE recusar a conexão.
- R10.5 Chaves e certificados do TLS do banco NÃO DEVEM ser versionados; DEVEM ser gerados na subida do ambiente.

### R11. SQL entregável e documentado
Como integrante que faz a entrega da disciplina, quero o SQL de todos os objetos organizado e explicado, para entregar e apresentar sem montar arquivos à mão.

- R11.1 Cada índice, consulta, view, função, procedimento e trigger DEVE estar em arquivo SQL próprio, com um cabeçalho que explica objetivo, justificativa semântica e quem o usa.
- R11.2 O SQL que roda na aplicação DEVE ser o mesmo dos arquivos, sem cópia (ADR-0009).
- R11.3 O sistema DEVE oferecer um comando que gera um arquivo único com todo o SQL da disciplina (criação, consultas e objetos), na ordem de execução.
- R11.4 Os identificadores DEVEM ser significativos (sem nomes como `x1` ou `a1`), seguindo a convenção de nomes do projeto.
- R11.5 Cada consulta, view, função, procedimento e trigger DEVE ter teste de integração contra PostgreSQL.

## Decisões (Rafael, 06/11/2026)
- **U6 · Situação cadastral (R5.3):** aprovada, com a precedência como está. Até a 007 manter a contagem de pendências, o valor `com_pendencias` não aparece.
- **U16 · Versão por trigger (R8):** aceita. O caso de uso da 006 deixa de incrementar a versão (emenda no design da 006).
- **Unidade já inativa (R6.4):** 200, sem alteração e sem auditoria (regra de 006/R3.6).
- **U4 · 30 tuplas:** tabelas de domínio fechado (distritos, áreas técnicas, tipos, papéis, permissões) ficam com menos de 30, com justificativa no README.
- **U5 · "D" do CRUD:** exclusão lógica em unidades e referências; exclusão física em equipamentos e serviços.
- **R9.2:** a 006 foi emendada (R7.2 e R7.3): o código de referência é editável e a correção é auditada.
- **U8:** o particionamento do `audit_log` saiu da 008 (design § Retenção; T5 removida).
- **Interface (U1):** fora desta spec; o front não é preocupação desta fase.

## Perguntas em aberto
- **Dependências:** a 011 depende das tabelas da 006 e de `users` (002/T2); a parte de API depende da 003. A R4.5 adianta a 008/R1 para 13/11.
- **Pontas na `fn_normalize_name` (R5.1; achado na 006/T2):** a expressão do design faz o `btrim` antes do `regexp_replace`. Sem segundo argumento, o `btrim` só tira o espaço comum (U+0020); um tab ou uma quebra de linha na ponta vira um espaço que fica no resultado (`'UPA  Ibura\t'` → `'upa ibura '`), contra "sem espaços nas pontas". Pôr o `btrim` por fora (`btrim(regexp_replace(lower(unaccent(...)), '\s+', ' ', 'g'))`) resolve. O espaço não separável (U+00A0) não sai nem no `unaccent` nem no `\s` do Postgres. Conferido num `postgres:17`. A `normalizar_nome` do domínio da 006 reproduz a expressão atual; se a 011/T2 mudar a ordem, muda junto (teste `tests/unit/registry/test_dominio_unidade.py`). **Resolvida (Rafael, 07/11/2026):** `btrim` por fora; design atualizado. A 011/T2 cria a função assim e a `normalizar_nome` da 006 acompanha.
- **Coluna gerada no trigger de versão (R8.2; achado na 011/T5):** num trigger BEFORE UPDATE, a coluna gerada `health_units.name_normalized` ainda não foi calculada e chega nula em `NEW` (conferido num `postgres:17`). Com o recorte do design (`to_jsonb(NEW) - '{pending_issues,version,updated_at}'`), `NEW` sempre difere de `OLD`, e até a mudança só em `pending_issues` incrementaria a versão, contra R8.2. A 011/T5 tirou também `name_normalized` da comparação: ela deriva de `name`, que continua comparado, então nenhuma alteração de dado deixa de incrementar (`migrations/sql/0011_05/01_fn_trg_health_units_version.sql`; teste `tests/integration/registry/test_versao_trigger.py::test_mudanca_so_nas_pendencias_nao_incrementa_a_versao`). O trigger de log (T7) é AFTER e já vê o valor calculado. Falta o Rafael confirmar e o design (§ `trg_health_units_version()`) ganhar a coluna na lista.
- **`FOR ROLE sgs` nos default privileges (R10.1; achado na 011/T3):** o design (§ Na 0011, item 2) escreve `ALTER DEFAULT PRIVILEGES FOR ROLE sgs`. `sgs` é o dono do banco no compose e no CI, mas nos testes de integração o dono é o superusuário do container (`test`), e lá o papel `sgs` não existe: a migração falharia. A 011/T3 usa `FOR ROLE CURRENT_USER`, que é sempre o papel que roda as migrações (o mesmo efeito no compose). Falta o Rafael confirmar e, se for o caso, ajustar o texto do design.
- **Funções de trigger anteriores à 0011 (R10.1; achado na 011/T3):** `audit_log_somente_insercao()` (0001) e `trg_roles_protect_system()` (0003) foram criadas antes dos default privileges e continuam com EXECUTE para PUBLIC. O PostgreSQL recusa chamar uma função de trigger fora de um trigger, então o risco prático é nulo, mas a letra de R10.1 ("NÃO DEVEM ser executáveis por qualquer usuário") não fica cumprida para elas. O design só pede o REVOKE nas rotinas da 0011, e a T3 não mexeu nelas. Proposta: um `REVOKE EXECUTE ... FROM PUBLIC` para cada uma numa revisão da 0011 (por exemplo, junto da T7). Falta a decisão do Rafael. A T7 não mexeu nelas.
- **Leitura do design no trigger de log (R7.3, R7.4; achado na 011/T7):** a 011/T7 seguiu o texto do design (§ `trg_registry_change_log()`) ao pé da letra em dois pontos que ele não detalha: (1) `pending_issues`, `version` e `updated_at` ficam fora do de/para em toda operação, não só no UPDATE (na inclusão, a versão 1 e as datas padrão não dizem nada ao Auditor); (2) `manager_name` sai como `"***"` em `de` e `para` sempre que aparece, inclusive na inclusão e na exclusão e quando está vazio, para o log não revelar nem se o nome estava preenchido. `name_normalized` entra no de/para: o trigger é AFTER e já vê a coluna calculada. Testes: `tests/integration/audit/test_log_banco.py::test_inclusao_registra_cada_coluna_com_de_nulo` e `::test_nome_do_gestor_fica_mascarado`. Falta o Rafael confirmar.
- **Escopo de `dashboard:read` nas consultas (R2.5; achado na 011/T11):** a história de R2 fala em cada perfil "no próprio escopo", mas a matriz (arquitetura-conceitual.md § 4, semeada na 0003) dá `dashboard:read` com escopo máximo G a todos os papéis que a têm, e pelo padrão da 003/T3 o G vale em todo lugar. Com os papéis semeados, então, `escopo_de_leitura(usuario, "dashboard:read")` é sempre global e as consultas não reduzem nada. A 011/T11 aplica o escopo (fragmento fixo) e o prova com um papel de teste que tem `dashboard:read` com máximo `distrito` (`tests/integration/dashboard/test_consultas_qualidade.py`). Falta o Rafael decidir se a matriz muda (por exemplo, A, D e U para `COORD_TECNICO`, `TECNICO_DISTRITAL` e `GESTOR_UNIDADE`) ou se fica como está (todos veem a rede inteira no dashboard).
- **Leituras do design nas rotas de R2 (achado na 011/T11; padrões adotados):** (1) `tipo` e `distrito` do `UnidadeResumoOut`, e `distrito` e `equipamento_tipo` do `ConciliacaoOut`, são os nomes (`unit_types.name`, `districts.name`, `equipment_types.name`), para leitura; os filtros `distrito` e `tipo` recebem os ids das referências; (2) "inexistente" (R2.9) é o id que não está na tabela de referência; distrito ou tipo desativado continua filtrável, porque as unidades dele seguem no cadastro; (3) a conciliação não filtra o status da unidade, como o design (§ Consultas); a lista de unidades sem serviço usa `status <> 'inativa'`, também do design, então a unidade em implantação entra. Falta o Rafael confirmar.
- **Conferência dos filtros e o teste de arquitetura da T20 (R2.9, R11.1; achado na 011/T11):** a conferência de distrito e tipo usa `district_exists.sql` e `unit_type_exists.sql`, em `dashboard/infrastructure/sql/` (R11.1, como a 006/T3 fez com `district_is_active.sql`). Elas leem só tabelas de referência, que não têm escopo, e por isso não levam o fragmento de escopo. O teste da T20 ("toda consulta do `dashboard` com o fragmento de escopo") precisa isentá-las, por exemplo exigindo o fragmento só nas consultas que leem o cadastro (`health_units` ou as views).
