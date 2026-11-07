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
- **Status de equipamento e de serviço (achado na T1):** o modelo de dados não lista os valores, então a 0006 deixa `equipments.status` e `services.status` sem CHECK (só o da unidade tem: `ativa`, `inativa`, `em_implantacao`). Os valores aceitos ficam para os schemas da T7 e da T8; se forem fixados, uma revisão nova põe o CHECK.
