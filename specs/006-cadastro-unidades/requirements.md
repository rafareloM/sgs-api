# 006 · Cadastro de unidades, equipamentos e serviços · Requisitos

- Status: Aprovado (Rafael, 07/11/2026)
- Rastreia: RF-01, RF-02, RF-09, RS-02, RS-05, RS-08; critérios 6.1 "cadastrar unidade do início ao fim", "localizar unidade por busca ou filtro"; reunião de 18/09/2026 (unidade × equipamento × serviço, "algo modular")

## Contexto
É o coração do produto: substituir a planilha REDE_SAUDE_RECIFE_GEO por um cadastro único. O cliente separa três entidades: **unidade** (autonomia administrativa), **equipamento** (pode ou não ser unidade) e **serviço** (dentro de unidade/equipamento ou "solto"). A Atividade 5 simplificou equipamento como lista dentro da unidade; aqui mantemos esse esforço na API, mas com modelo que permite crescer.

## Fora do escopo
- Workflow de proposta e validação (RF-04) — alteração autorizada é aplicada direto e auditada.
- Integração e comparação com CNES (RF-05).
- Infraestrutura interna da unidade (salas, consultórios) — extensão futura.
- Importação de planilha (ver spec 010 para massa de dados).

## Histórias e critérios

### R1. Cadastrar unidade
Como Gestor de Dados (ou Coordenador Técnico da área), quero cadastrar uma unidade para que ela passe a existir na base única.

- R1.1 QUANDO um usuário com `unidade:create` no escopo da área do tipo informado envia uma unidade válida, o sistema DEVE criá-la e responder 201 com o recurso completo.
- R1.2 O sistema DEVE exigir: nome, tipo de unidade, distrito sanitário, endereço com CEP e status.
- R1.3 SE já existir unidade com o mesmo CNES, ENTÃO o sistema DEVE responder 409 indicando a unidade existente.
- R1.4 SE já existir unidade com o mesmo nome normalizado (sem acento, caixa e espaços extras) no mesmo distrito, ENTÃO o sistema DEVE responder 409.
- R1.5 O sistema DEVE aceitar unidade sem CNES (serviços municipais que não estão no CNES) e marcar `cnes_pendente = true`.
- R1.6 QUANDO a unidade é criada, o sistema DEVE registrar `unidade.criada` na auditoria com todos os campos.

### R2. Consultar e buscar
Como qualquer usuário de negócio, quero encontrar uma unidade sem percorrer a lista inteira.

- R2.1 QUANDO o usuário lista `GET /unidades`, o sistema DEVE responder com paginação (padrão 20, máximo 100) e total de itens.
- R2.2 O sistema DEVE filtrar por texto livre (`q`) em nome e CNES, ignorando acentos e caixa.
- R2.3 O sistema DEVE filtrar por tipo, área técnica, distrito, status e `com_pendencias`, combináveis.
- R2.4 O sistema DEVE ordenar por nome (padrão), distrito ou data de atualização.
- R2.5 QUANDO o usuário pede `GET /unidades/{id}`, o sistema DEVE devolver a unidade com equipamentos e serviços vinculados.
- R2.6 O sistema DEVE aplicar o escopo de leitura do usuário em listagens e detalhes (spec 003).
- R2.7 O sistema DEVE responder a busca em menos de 3 s para 95% das requisições com 1.000 unidades (RNF-01).

### R3. Atualizar unidade
Como Gestor de Unidade (ou técnico do distrito), quero corrigir os dados da minha unidade.

- R3.1 QUANDO um usuário com `unidade:update` no escopo da unidade envia `PATCH` válido, o sistema DEVE aplicar apenas os campos enviados e responder 200.
- R3.2 O sistema DEVE exigir `If-Match` com a versão atual (ETag); SE a versão estiver desatualizada, ENTÃO DEVE responder 412 (evita sobrescrever alteração de outra pessoa).
- R3.3 SE o usuário não tiver o escopo, ENTÃO o sistema DEVE responder 403 e nada DEVE mudar.
- R3.4 O sistema NÃO DEVE permitir que `GESTOR_UNIDADE` ou `TECNICO_DISTRITAL` alterem distrito, tipo ou CNES da unidade (campos estruturais, só `GESTOR_DADOS` e `COORD_TECNICO`).
- R3.5 QUANDO a atualização é aplicada, o sistema DEVE registrar `unidade.atualizada` com a lista de campos `{campo, de, para}`.
- R3.6 SE nenhum valor mudar, ENTÃO o sistema DEVE responder 200 sem gerar registro de auditoria.

### R4. Desativar
- R4.1 QUANDO um usuário com `unidade:deactivate` desativa uma unidade com motivo, o sistema DEVE mudar o status para `inativa` e auditar.
- R4.2 O sistema NÃO DEVE apagar unidades fisicamente.

### R5. Equipamentos
- R5.1 O sistema DEVE permitir listar, adicionar, alterar e remover equipamentos de uma unidade em `/unidades/{id}/equipamentos`, com a permissão `equipamento:write` no escopo da unidade.
- R5.2 O sistema DEVE permitir equipamento sem unidade (ex.: UTI móvel) apenas para `GESTOR_DADOS`, em `/equipamentos`.
- R5.3 Toda mudança em equipamento DEVE ser auditada no nível da unidade (decisão da Atividade 5 §3.2).

### R6. Serviços
- R6.1 O sistema DEVE permitir listar, adicionar, alterar e remover serviços de uma unidade em `/unidades/{id}/servicos`, com `servico:write` no escopo da unidade.
- R6.2 O sistema DEVE permitir serviço "solto" (sem unidade, ex.: Sala de Vacinação do Shopping) apenas para `GESTOR_DADOS`.
- R6.3 O sistema DEVE indicar se o serviço consta no CNES (`no_cnes`).
- R6.4 QUANDO a unidade é renomeada, os serviços vinculados DEVEM refletir o novo nome sem edição adicional (vínculo por id, nunca por nome).

### R7. Tabelas de referência
- R7.1 O sistema DEVE expor `GET /referencias/distritos`, `/tipos-unidade`, `/areas-tecnicas`, `/tipos-servico` e `/tipos-equipamento` para preencher formulários.
- R7.2 Apenas `GESTOR_DADOS` DEVE poder incluir, alterar (inclusive o código) ou desativar itens de referência.
- R7.3 QUANDO o código de um tipo de equipamento é corrigido, os equipamentos desse tipo DEVEM passar a usar o código novo, e o sistema DEVE registrar `referencia.atualizada` na auditoria com a quantidade de equipamentos afetados (spec 011, R9.2).

## Perguntas em aberto
- Lista oficial de distritos sanitários e tipos de unidade (pedir ao Sérgio a aba de convenções da planilha).
- Campos estruturais (R3.4) estão corretos para o fluxo da Secretaria?
- **Tipos de equipamento e de serviço (achado na T1):** sem lista oficial, a 0006 semeia só os exemplos de `steering/product.md` e do modelo de dados: equipamento `UTI_MOVEL`, `MATERNIDADE` e `POLICLINICA`; serviço `FARMACIA`, `FARMACIA_FAMILIA`, `SALA_VACINA` e `ESPACO_MAE_CORUJA`. Os distritos (DS-I a DS-VIII) e os tipos de unidade seguem a pergunta acima. Confirmar com o cliente junto com ela; o Gestor de Dados ajusta pela API (R7.2).
- (006/T3) Como o 409 "indica a unidade existente" (R1.3)? (padrão adotado: membro de extensão `unidade_existente_id` no problem+json, RFC 9457 § 3.2; o 409 por nome no distrito, R1.4, também o traz)
- (006/T3) `cnes_pendente` (R1.5) é coluna? (padrão adotado: não; a resposta o deriva de `cnes` nulo, a mesma regra da `fn_registration_status` da 011)
- (006/T3) Qual o formato de `opening_hours` (JSONB no modelo de dados)? (padrão adotado: fora do `UnidadeCreate` até haver formato definido; a resposta traz `horario_funcionamento` nulo)
- (006/T3) Tipo de unidade ou distrito desativado aceita unidade nova? (padrão adotado: não; 422 apontando o campo, como se não existisse)
- (006/T3) O que é "todos os campos" em `unidade.criada` (R1.6)? (padrão adotado: os campos de negócio, com os nomes das colunas, `de` nulo, inclusive os vazios; ficam de fora `name_normalized`, `version`, `pending_issues` e as datas, mantidos pelo banco. `manager_name` vai sem máscara; mascarar na exibição é da 008/R2.3)
- (006/T3) O 403 de quem tem `unidade:create` só em outra área é auditado? (padrão adotado: sim, `acesso.negado` sem entidade, porque a unidade não chegou a existir, 003/R4.6)
- (006/T3) A 201 leva cabeçalhos? (padrão adotado: `Location` com a rota da unidade e `ETag` com a versão entre aspas, `"1"`, a mesma do `If-Match` da T5)
- (006/T6) Que limites tem o motivo da desativação (R4.1)? (padrão adotado: obrigatório, de 1 a 500 caracteres depois de tirar os espaços das pontas, guardado em `metadata.motivo` de `unidade.desativada`; corpo com campo a mais → 422)
- (006/T6, 011/T16) O motivo enviado para uma unidade que já está inativa fica guardado? (padrão adotado: não; nada muda, então não há auditoria, 011/R6.4, e o motivo é descartado)
- (006/T9, 011/T18) Leituras adotadas nas rotas de referência (R7): (1) o `GET` lista ativos e desativados, com `ativo`, pela ordem do id (a da semeadura), para o formulário escolher os ativos e o Gestor poder reativar; (2) desativar e reativar é `PATCH` com `ativo` (exclusão lógica, sem rota própria) e audita `referencia.atualizada`; incluir audita `referencia.criada`; `entity_type` é a tabela (`distrito`, `area_tecnica`, `tipo_unidade`, `tipo_equipamento`, `tipo_servico`) e o de/para usa os nomes da API (`codigo`, `nome`, `ativo`, `area_tecnica_id`); (3) o tipo de unidade aceita trocar a área técnica (muda o escopo do Coordenador Técnico sobre as unidades do tipo), e área inexistente ou desativada dá 422, como o distrito na T3; (4) `equipamentos_afetados` só vai nos metadados quando o código de um tipo de equipamento muda, inclusive com 0; (5) o código só tem limite de tamanho (20 no distrito, 50 nos outros), sem formato fixo; (6) PATCH sem mudança não audita. Falta o Rafael confirmar. A T5 da 003 (rotas protegidas) precisa aceitar os `GET /referencias/*`, que só exigem autenticação (design § Rotas), como o `GET /me`.
- (006/T5) O que responder ao `PATCH` sem `If-Match` (R3.2)? (padrão adotado: 428 Precondition Required, RFC 6585 § 3, `urn:sgs:problema:versao-exigida`; um `If-Match` que não é o `ETag` de uma versão, como `*`, `W/"1"` ou uma lista, não casa com a versão atual e dá 412)
- (006/T5) Como o 403 "aponta os campos" estruturais (R3.4)? (padrão adotado: membro de extensão `campos` no problem+json, com os nomes da API, como `["distrito_id", "cnes"]`; o `acesso.negado` leva a unidade. Nada da requisição é gravado, nem os outros campos enviados)
- (006/T5) Com escopo de área, o Coordenador Técnico pode mudar o tipo da unidade para um de outra área técnica, tirando-a do próprio escopo? (resolvida na revisão do /implement-spec: não. Como no cadastro (R1.1), o caso de uso confere também a área do tipo novo; sem escopo nela, 403 auditado com a extensão `campos`, como o 403 estrutural. Teste: `test_coordenador_nao_troca_o_tipo_para_um_de_area_fora_do_seu_escopo`)
- (006/T5) Campo opcional enviado nulo no `PATCH`? (padrão adotado: apaga o valor; CNES nulo deixa a unidade pendente, R1.5, e conta como alteração estrutural. Os obrigatórios do cadastro, R1.2, não aceitam nulo: 422 apontando o campo. Tipo ou distrito novo inexistente ou desativado: 422, como no cadastro. CNES ou nome repetido: 409 com `unidade_existente_id`, como no cadastro)
- (006/T5) Ordem e nomes dos campos em `unidade.atualizada` (R3.5)? (padrão adotado: os nomes das colunas, como em `unidade.criada`, na ordem das colunas, seja qual for a do corpo; `manager_name` sem máscara, como na criação)
- (006/T7) Leituras adotadas nos equipamentos (R5): (1) status aceitos `ativo`, `inativo` e `em_implantacao`, os da unidade no masculino, só no schema; a resposta devolve o que estiver no banco, e o CHECK fica para uma revisão nova quando o cliente confirmar a lista; (2) o tipo vai pelo código (`tipo_equipamento_codigo`), como a FK, e tipo inexistente ou desativado dá 422 apontando o campo, como o tipo de unidade na T3 (no PATCH, só se o tipo muda); (3) campos: `nome`, `cnes` (7 dígitos, opcional), `quantidade` (inteiro ≥ 1, padrão 1, o do banco) e `status`; no PATCH os obrigatórios não aceitam nulo, `cnes` nulo apaga, e a unidade do equipamento não muda; (4) eventos `unidade.equipamento_criado`, `_atualizado` e `_removido`, com a unidade como entidade, os campos com os nomes da API e o prefixo `equipamento.` (como o exemplo `equipamento.nome` da 011/T14), `de` nulo na criação e `para` nulo na remoção, e o id do equipamento em `metadata.equipamento_id`; PATCH sem mudança não audita; (5) equipamento sem unidade é auditado como `equipamento.criado`, com o próprio equipamento como entidade (`entity_type = 'equipamento'`) e os campos sem prefixo, porque não há unidade para levar o evento; (6) `equipamento:write` com escopo de área, distrito ou unidade passa no `require` de `/equipamentos`, e o caso de uso exige o escopo global (403 `acesso.negado` sem entidade); (7) as listagens devolvem uma lista simples pela ordem de cadastro, sem paginação (poucos por unidade); (8) equipamento de outra unidade na rota dá 404, como se não existisse; a remoção responde 204 e o `POST` na unidade traz `Location` com a rota do PATCH/DELETE (o `POST /equipamentos` não traz, porque não há rota do equipamento sem unidade). Em aberto: o design só dá `GET/POST /equipamentos`, então alterar e remover equipamento sem unidade (R5.2 "permitir equipamento sem unidade") não tem rota; e se equipamento pode ser adicionado a unidade inativa (hoje pode). Falta o Rafael confirmar.
- (006/T8) Leituras adotadas nos serviços (R6), as mesmas da T7 onde valem: (1) status `ativo`, `inativo` e `em_implantacao`, só no schema; (2) o tipo vai pelo id (`tipo_servico_id`), como a FK e o detalhe da unidade, e tipo inexistente ou desativado dá 422 apontando o campo; (3) campos: `nome`, `tipo_servico_id`, `equipamento_id` (opcional) e `no_cnes` (booleano, padrão `false`, o do banco, R6.3) e `status`; no PATCH só `equipamento_id` aceita nulo (desliga o serviço do equipamento), e a unidade do serviço não muda; (4) eventos `unidade.servico_criado`, `_atualizado` e `_removido`, com a unidade como entidade, os campos com os nomes da API e o prefixo `servico.`, o id do serviço em `metadata.servico_id`; o solto grava `servico.criado` com o próprio serviço como entidade; (5) `servico:write` com escopo não global passa no `require` de `/servicos`, e o caso de uso exige o global (403 `acesso.negado` sem entidade); (6) listas simples pela ordem de cadastro; serviço de outra unidade na rota dá 404; remoção 204; `Location` só no `POST` da unidade; (7) R6.4 é atendido pelo vínculo por id: renomear a unidade não toca no serviço nem audita nada nele, e a resposta do serviço leva `unidade_id`, não o nome. Novas em aberto: (a) o equipamento do serviço tem de ser da mesma unidade (senão 422 em `equipamento_id`); e o serviço solto pode estar num equipamento sem unidade, como a UTI móvel (adotado: sim, mas o cabeçalho da `services` chama de solto só o que não tem unidade nem equipamento); (b) como na T7, o design só dá `GET/POST /servicos`, então alterar e remover serviço solto não tem rota. Falta o Rafael confirmar.
- **Status de equipamento e de serviço (achado na T1):** o modelo de dados não lista os valores, então a 0006 deixa `equipments.status` e `services.status` sem CHECK (só o da unidade tem: `ativa`, `inativa`, `em_implantacao`). Os valores aceitos ficam para os schemas da T7 e da T8; se forem fixados, uma revisão nova põe o CHECK.
- (006/T4) Que ordem vale com texto livre e sem `ordenar` (R2.4 diz nome como padrão; o design § Busca, `similarity` quando há `q`)? (padrão adotado: sem `q`, nome; com `q` e sem `ordenar`, a mais parecida primeiro; `ordenar` explícito sempre vale. `distrito` ordena pelo nome do distrito e depois pelo da unidade; `atualizacao`, da mais recente para a mais antiga; o nome normalizado e o id desempatam)
- (006/T4) Filtro por tipo, área ou distrito que não existe? (padrão adotado: lista vazia, sem 422; id fora do formato, de 1 a 32767, dá 422. `q` só com espaços vale como sem `q`; `%` e `_` são procurados como caracteres)
- (006/T4) Que campos vão em cada item da listagem e quais serviços entram no detalhe (R2.1, R2.5)? (decisão restritiva da revisão do /implement-spec, `steering/security.md` § LGPD, "na dúvida, o mais restritivo": o item é a `UnidadeNaListaOut`, a unidade sem `nome_gestor` e sem `telefone`, para a listagem não expor em massa o nome e o contato do gestor de cada unidade; os dois continuam no detalhe `GET /unidades/{id}`, que é a unidade que a pessoa abriu, e na resposta do cadastro e da alteração. O telefone é o da unidade, não necessariamente pessoal, mas entrou na mesma regra por dúvida. Teste: `test_buscar_unidades.py::test_item_da_lista_nao_traz_o_gestor_nem_o_telefone_e_o_detalhe_traz`. Falta o Rafael confirmar se a listagem precisa desses campos, por exemplo para uma tela de contatos; o detalhe soma os equipamentos e os serviços com `unit_id` da unidade, em ordem de nome, e devolve o `ETag` da versão)
