# 014 · Front-end do diretório e dos relatórios · Requisitos

- Status: Aprovado (G1: Rafael, rafareloM, dono, em 26/11/2026, com as recomendações de P1 a P3 aceitas; registro do agente por autorização expressa na sessão de trabalho)
- Rastreia: RF-07 (parcial), RS-01, RS-02; spec 005 (R1.1, R1.2, R1.4, R1.5, R3.1 a R3.5, R5.3, R5.4), spec 004 (R1.1, R1.9 a R1.11, R1.14), spec 003 (R3.1, R3.2, R2.5); spec 012 (R1.2, R1.6, R3.1 a R3.4, R13); mapa #25
- Dono humano: Rafael (rafareloM)
- Origem: mapa #25 "Front-end do diretório e dos relatórios (004/005)" e as decisões de partida de 26/11/2026 registradas nele

## Contexto
As specs 004 e 005 entraram na `main` (#24) só com API: relatórios, sincronização do diretório e grupos espelhados não têm tela, e a demonstração depende de `curl`. Esta spec dá tela a essas rotas no front da 012 (JS sem build, ADR-0010), sem mudar backend, contrato nem a matriz RBAC. A 012 é do Vinicius; esta é separada, com nota de referência no design da 012, como fez a 004/T10.

## Fora do escopo
- Tela de Atribuições (`/admin/atribuicoes`, spec 003): `#/papeis` segue "em implantação".
- Conferir a assinatura no navegador (WebCrypto): a tela mostra os dados e aponta o roteiro de verificação.
- O botão "Exportar lista" da lista de unidades (DF10 da 012): segue "em desenvolvimento".
- Mudanças no backend, no contrato (`contracts/openapi.yaml`) ou na matriz RBAC.
- Nomes de pessoas na lista de relatórios e nas execuções: a API devolve só ids (LGPD, 004 § ConflitoOut).

## Histórias e critérios
Convenções: "o front" é a interface da 012; toda ação depende da resposta da API (012/R3.4); os papéis são os da 003.

### R1. Pedir relatório
Como Gestor de Dados (ou Coordenação Técnica, Diretoria, Auditoria), quero pedir um relatório pela tela para não depender de `curl`.

- R1.1 O front DEVE oferecer a tela Relatórios (`#/relatorios`) no menu a quem tem `relatorio:export`, e "sem acesso" a quem não tem (012/R3.3).
- R1.2 QUANDO o usuário envia o formulário com tipo, formato e filtros, o front DEVE chamar `POST /relatorios` com os filtros que a API aceita para o tipo (005/R1.2) e, no 202, mostrar o pedido na lista com o status `pendente` (005/R1.1).
- R1.3 O front DEVE oferecer o tipo "Trilha de auditoria" só a quem tem `auditoria:read` (005/R1.4); o tipo "Inventário de unidades" a quem tem `unidade:read`.
- R1.4 Para o inventário, o front DEVE oferecer os filtros distrito, área técnica, tipo de unidade e situação, todos opcionais, com os nomes das tabelas de referência.
- R1.5 Para a trilha, o front DEVE exigir a data inicial e a final (dias no fuso de Recife, a final incluída) e oferecer prefixo da ação e tipo de entidade, opcionais.
- R1.6 SE a API responder 422, ENTÃO o front DEVE mostrar cada erro no campo correspondente, ou a mensagem geral quando o erro não tiver campo na tela (005/R1.5).
- R1.7 SE a API responder 503, ENTÃO o front DEVE informar que a exportação não está configurada no servidor.

### R2. Acompanhar e baixar
Como quem pediu um relatório, quero ver quando ele fica pronto e baixá-lo.

- R2.1 O front DEVE listar os pedidos (`GET /relatorios`), do mais recente ao mais antigo, com tipo, formato, filtros em texto, status, quem pediu ("Você" ou o id), quando foi pedido, quando ficou pronto, tamanho e validade, com paginação (005/R3.5).
- R2.2 ENQUANTO houver na lista pedido `pendente` ou `gerando`, o front DEVE atualizá-la a cada 3 s, por no máximo 2 min; DEVE parar ao sair da tela e oferecer o botão "Atualizar" em qualquer momento.
- R2.3 QUANDO o usuário com `relatorio:download` clica "Baixar" num pedido `concluido` e não vencido, o front DEVE pedir `GET /relatorios/{id}/download` e abrir a URL devolvida no navegador, sem exibi-la nem guardá-la (005/R3.2, D005-1).
- R2.4 O front NÃO DEVE oferecer "Baixar" em pedido não concluído, vencido, ou a quem não tem `relatorio:download`; SE a API responder 409, 403 ou 503 ao baixar, ENTÃO o front DEVE mostrar a mensagem da API num aviso.
- R2.5 SE o pedido estiver `falhou`, ENTÃO o front DEVE mostrar a mensagem genérica da API (005/R2.6) e permitir pedir de novo com os mesmos filtros.

### R3. Integridade do relatório
Como quem recebe o arquivo, quero os dados para conferir a assinatura fora da plataforma.

- R3.1 QUANDO o usuário abre o detalhe de um pedido `concluido`, o front DEVE mostrar o SHA-256, o algoritmo, o `kid` e a assinatura devolvidos por `GET /relatorios/{id}` (005/R5.3).
- R3.2 O front DEVE oferecer um botão que copia para a área de transferência o objeto `integridade` em JSON, no formato que o roteiro `docs/operacao/verificar-relatorio.md` lê (`integridade.json`).
- R3.3 O front DEVE apontar o caminho do roteiro de verificação e o link das chaves públicas (`/.well-known/relatorios-jwks.json`, 005/R5.4).

### R4. Sincronização do diretório
Como Admin TI, quero disparar e acompanhar a sincronização LDAP pela tela.

- R4.1 O front DEVE oferecer a tela Diretório (`#/diretorio`) no menu a quem tem `diretorio:sync` ou `papel:assign`, com a aba Execuções (só com `diretorio:sync`) e a aba Grupos (só com `papel:assign`).
- R4.2 QUANDO o Admin TI clica "Sincronizar agora", o front DEVE chamar `POST /admin/diretorio/sincronizar` e, no 202, mostrar a execução na lista com o status `em_andamento` (004/R1.1).
- R4.3 SE a API responder 409, ENTÃO o front DEVE avisar que já há uma sincronização em andamento, sem erro de tela (004/R1.11); SE responder 503, ENTÃO DEVE informar que o LDAP não está configurado.
- R4.4 O front DEVE listar as execuções (`GET /admin/diretorio/execucoes`), da mais recente para a mais antiga, com status, início, fim, contagens de usuários e de grupos (criados, atualizados, desativados) e número de conflitos, com paginação (004/R1.9).
- R4.5 QUANDO o Admin TI abre uma execução, o front DEVE mostrar as contagens, os conflitos (tipo, `external_id`, id da conta existente) e a mensagem de erro genérica, quando houver (004/R1.10, R4.2).
- R4.6 ENQUANTO houver execução `em_andamento`, o front DEVE atualizar a lista como em R2.2.

### R5. Mapeamentos grupo→papel
Como Admin TI, quero mapear um grupo do diretório para um papel sem montar o `grupo_id` à mão.

- R5.1 A aba Grupos DEVE listar os grupos espelhados (`GET /admin/diretorio/grupos`) com nome, origem, membros ativos e situação, busca por trecho do nome, filtro de origem e paginação (004/R1.14).
- R5.2 A aba Grupos DEVE listar os mapeamentos (`GET /admin/mapeamentos-grupo`) com o nome do grupo, o papel e o escopo.
- R5.3 QUANDO o Admin TI escolhe um grupo, um papel (`GET /admin/papeis`) e, se o papel exigir, o id do escopo, o front DEVE chamar `POST /admin/mapeamentos-grupo` com o escopo exigido pelo papel e, no 201, mostrar o mapeamento na lista (003/R3.1).
- R5.4 SE a API responder 403 por segregação de funções, 409 ou 422, ENTÃO o front DEVE mostrar a mensagem da API (no campo, quando houver) sem fechar o formulário (003/R2.5).
- R5.5 QUANDO o Admin TI confirma a remoção de um mapeamento, o front DEVE chamar `DELETE /admin/mapeamentos-grupo/{id}` e tirá-lo da lista no 204, avisando que as atribuições derivadas saem e as diretas ficam (003/R3.2, R3.3).

### R6. Qualidade comum
- R6.1 As três telas DEVEM seguir a 012: estados de carregamento, vazio e erro (012/R1.6), escape de todo texto da API (012/R15.1), aparência e tema do protótipo (012/R1.2), datas no fuso de Recife.
- R6.2 Cada critério de R1 a R5 DEVE ter um teste Playwright em `tests/e2e_front/` contra o compose com SeaweedFS e `slapd` de laboratório, sem simular a API, salvo os estados que o laboratório não produz (503, falha da geração).

## Perguntas em aberto
Respondidas no G1 (Rafael, 26/11/2026): as recomendações de P1, P2 e P3 foram aceitas.

- (P1, recomendação do agente) O Admin TI não tem `unidade:read`, então não lê as tabelas de referência nem as unidades: o escopo de um mapeamento (distrito, área ou unidade) é digitado como id, e a API o confere (422). Mostrar nomes pediria emenda na matriz da 003. Recomendação: aceitar o id digitado nesta spec.
- (P2, recomendação do agente) O map pedia "copiar assinatura"; R3.2 copia o objeto `integridade` inteiro (que contém a assinatura), porque é o arquivo que o roteiro de verificação lê. Recomendação: aceitar.
- (P3) Com o item Diretório antes de Papéis no menu, o início do Admin TI passa de `#/papeis` ("em implantação") para `#/diretorio` (012/R3.5, primeira tela do menu). Recomendação: aceitar e ajustar `test_perfis.py`.
