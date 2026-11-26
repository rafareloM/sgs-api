# 005 · Exportação de relatórios para S3 · Requisitos

- Status: Aprovado (G1: Rafael, rafareloM, dono, em 24/11/2026, com as recomendações das perguntas de 24/11/2026 aceitas; registro do agente por autorização expressa na sessão de trabalho)
- Rastreia: RF-07 (parcial), RNF-05, RS-03, RS-04, RS-05, requisito obrigatório "exportação de relatórios para armazenamento em nuvem com mecanismos de autenticação avançados", objetivo "assinaturas digitais e certificados" da disciplina de Criptografia (R5)
- Dono humano: Vinicius (ViniciusVbm) e Rafael (rafareloM), como responsáveis pelo projeto: a spec não tinha dono registrado (`steering/sdd-workflow.md` § Dono da spec). Linha registrada na revisão de 09/11/2026; Rafael acrescentado em 24/11/2026.

## Contexto
Relatórios avançados estão fora do MVP (Requisitos Esperados §2.2). Esta spec entrega o mínimo que cumpre o requisito obrigatório: dois relatórios simples exportados para S3 com credenciais temporárias, criptografia e download controlado. Ver ADR-0005.

## Fora do escopo
- PDF, gráficos, agendamento de relatórios, envio por e-mail.

## Histórias e critérios

### R1. Solicitar relatório
Como Gestor de Dados, quero exportar o inventário de unidades para compartilhar com outras áreas.

- R1.1 QUANDO um usuário com `relatorio:export` solicita `POST /relatorios` com tipo, formato e filtros válidos, o sistema DEVE responder 202 com o id e status `pendente`.
- R1.2 O sistema DEVE oferecer os tipos `inventario_unidades` e `trilha_auditoria`, nos formatos `csv` e `xlsx`.
- R1.3 O sistema DEVE gerar o relatório apenas com os dados dentro do escopo de leitura de quem pediu, e registrar esse escopo no pedido.
- R1.4 SE o usuário pedir `trilha_auditoria` sem `auditoria:read`, ENTÃO o sistema DEVE responder 403.
- R1.5 SE os filtros forem inválidos (ex.: período maior que 366 dias), ENTÃO o sistema DEVE responder 422.

### R2. Envio para a nuvem
- R2.1 O sistema DEVE enviar o arquivo usando credenciais temporárias obtidas por STS `AssumeRole`, com `ExternalId` e `RoleSessionName` contendo o id do usuário, válidas por no máximo 15 minutos.
- R2.2 O sistema NÃO DEVE usar chaves de acesso fixas quando `APP_ENV=prod`.
- R2.3 O sistema DEVE enviar com criptografia do lado do servidor (`aws:kms` em prod; `AES256` aceito em dev) e checksum SHA-256.
- R2.4 O sistema DEVE gravar o objeto na chave `reports/{aaaa}/{mm}/{tipo}/{id}.{formato}`, sem dados pessoais no nome.
- R2.5 QUANDO o envio termina, o sistema DEVE marcar o pedido como `concluido` com tamanho e hash, e auditar `relatorio.exportado`.
- R2.6 SE a geração ou o envio falhar, ENTÃO o sistema DEVE marcar `falhou` com mensagem genérica, registrar o erro detalhado no log e permitir nova tentativa.
- R2.7 O sistema DEVE usar HTTPS em toda comunicação com o armazenamento.
- R2.8 QUANDO o envio termina, o sistema DEVE conferir na resposta do armazenamento que o objeto foi gravado com a criptografia exigida (R2.3) e com o checksum enviado; SE não conferir, ENTÃO o sistema DEVE remover o objeto e tratar como falha (R2.6). (novo, 24/11/2026)
- R2.9 SE a API iniciar com `APP_ENV=prod` sem o papel a assumir, sem o `ExternalId` ou sem a chave KMS, ou com chave de acesso fixa configurada, ENTÃO o sistema DEVE recusar iniciar (R2.1–R2.3). (novo, 24/11/2026)

### R3. Consultar e baixar
- R3.1 QUANDO o solicitante consulta `GET /relatorios/{id}`, o sistema DEVE devolver o status.
- R3.2 QUANDO um usuário com `relatorio:download` pede `GET /relatorios/{id}/download` de um relatório concluído, o sistema DEVE responder 200 com uma URL pré-assinada válida por 5 minutos e o instante em que ela vence. (revisto em 24/11/2026; antes: 307 para a URL; motivo na revisão abaixo)
- R3.3 O sistema DEVE permitir o download apenas ao solicitante ou a quem tenha escopo igual ou maior que o do relatório.
- R3.4 O sistema DEVE auditar `relatorio.baixado`.
- R3.5 QUANDO o usuário lista `GET /relatorios`, o sistema DEVE mostrar os pedidos dele (ou todos, para `GESTOR_DADOS`).
- R3.6 A URL pré-assinada DEVE usar o endereço público do armazenamento, acessível pelo navegador de quem baixa, e NÃO DEVE expor endereço interno da rede de serviços. (novo, 24/11/2026)

### R4. Conteúdo
- R4.1 O CSV DEVE ser UTF-8 com BOM e separador `;`, para abrir corretamente no Excel em português.
- R4.2 O sistema DEVE neutralizar valores iniciados por `=`, `+`, `-` ou `@` (prevenção de injeção de fórmula em CSV/XLSX).
- R4.3 A trilha de auditoria exportada NÃO DEVE conter valores marcados como sensíveis.

### R5. Assinatura digital
Como quem recebe um relatório exportado, quero conferir que ele saiu da plataforma e não foi alterado depois.

Proposto em 06/11/2026, a pedido do Rafael, para cobrir o objetivo "assinaturas digitais e certificados" da disciplina de Criptografia.

- R5.1 QUANDO a geração de um relatório termina, o sistema DEVE assinar digitalmente o hash SHA-256 do arquivo com uma chave privada da API e guardar a assinatura, o algoritmo e o identificador da chave (`kid`) junto com o pedido.
- R5.2 A chave que assina relatórios DEVE ser diferente da chave que assina os tokens de acesso (spec 002).
- R5.3 QUANDO um usuário com acesso ao relatório consulta `GET /relatorios/{id}` de um relatório concluído, o sistema DEVE devolver também a assinatura, o algoritmo, o `kid` e o hash.
- R5.4 O sistema DEVE publicar as chaves públicas de verificação de relatórios, identificadas por `kid`, para que a assinatura possa ser conferida fora da API.
- R5.5 O sistema DEVE manter verificáveis as assinaturas feitas com chaves anteriores depois de uma troca de chave.

### R6. Ambiente de demonstração
Como integrante do grupo, quero demonstrar a exportação no ambiente local sem depender de conta AWS.

Novo em 24/11/2026. A spec 001 (R1.1) deixou o S3 local do compose para esta spec, mas nenhum critério o pedia: a T8 rastreava só a R2.7.

- R6.1 QUANDO alguém sobe o ambiente local seguindo o README, o sistema DEVE subir também um armazenamento compatível com S3, com o bucket de relatórios criado, que a API acessa só por HTTPS com certificado validado (R2.7).
- R6.2 O ambiente local DEVE expor o armazenamento ao navegador do host só por HTTPS, no endereço público usado nas URLs pré-assinadas (R3.6), sem publicar as portas internas do armazenamento.
- R6.3 O ambiente local DEVE permitir demonstrar de ponta a ponta: pedido, geração, envio com criptografia e checksum conferidos (R2.8) e download do arquivo pelo navegador do host (R3.2, R3.6).

## Perguntas em aberto
- A chave pública de relatórios é distribuída como certificado X.509 autoassinado da plataforma ou só como chave pública (JWK)? Certificado ICP-Brasil fica fora do alcance do projeto.
- O grupo terá uma conta AWS para a demonstração (AWS Educate/Academy)? Se não, a demo usa SeaweedFS.
- Por quanto tempo os relatórios ficam no bucket? (padrão: regra de ciclo de vida de 90 dias)
- (revisão de 09/11/2026, agente; aguarda o dono) A R5 (assinatura digital, proposta em 06/11/2026) não tem design nem tarefa: o `design.md` e o `tasks.md` cobrem só R1 a R4. Falta decidir o algoritmo, onde a chave fica, a rota que publica as chaves públicas (R5.4) e a tarefa. Proposta: ECDSA P-256 (ES256), como os tokens, mas com chave própria em `secrets/` (R5.2), e chaves públicas em JWK numa rota pública; isso também responde a primeira pergunta acima com "JWK".
- (revisão de 09/11/2026, agente; aguarda o dono) Recomendações para as perguntas acima, a confirmar pelo grupo: demonstração com SeaweedFS no compose, sem depender de conta AWS; ciclo de vida de 90 dias.
- (revisão de 09/11/2026, agente; aguarda o dono) O ADR-0005 (exportação para S3), base desta spec, está `Proposto`. Convém aceitá-lo junto com a aprovação dos requisitos.
- (revisão de 24/11/2026, agente; aguarda o dono) Criptografia no SeaweedFS. A R2.8 e a R6.3 dependem de o armazenamento local aplicar e informar a criptografia `AES256`, e isso ainda não foi conferido na versão do SeaweedFS que entra no compose. Recomendação: conferir na primeira hora da T8. Se não aplicar, registrar aqui antes do G2, com as opções: outro armazenamento compatível, ou aceitar no dev só a conferência do checksum, o que deixa a criptografia sem demonstração local.
- (revisão de 24/11/2026, agente; aguarda o dono) Validação em produção. O item "autenticação S3 em ambiente de produção" do checklist só se comprova numa conta AWS. Sem conta, a evidência é a R2.1 com moto (`AssumeRole` com `ExternalId` e sessão de até 15 minutos), a R2.9 e o documento da T7. Recomendação: havendo conta, uma tarefa opcional de evidência depois do G3. Antes, confirmar que a conta permite criar papel IAM e chave KMS, o que contas de laboratório costumam restringir.
- (005/T6, 26/11/2026, agente; aguarda o dono) `AUDITOR` e o inventário. O design § Escopo dos relatórios diz que o `AUDITOR` "não tem `unidade:read`, então só exporta a trilha", mas a semeadura da 0003 (`MATRIZ`) dá `unidade:read` G ao `AUDITOR`. A T6 seguiu a regra D005-12 (permissão de dados do tipo), sem regra a mais: hoje o `AUDITOR` exporta o inventário, e o 403 da R1.4 é testado com a `DIRETORIA`, que não tem `auditoria:read`. Opções: (a) aceitar e corrigir a frase do design; (b) tirar `unidade:read` do `AUDITOR` na semeadura (muda a 003); (c) regra própria da 005 para o `AUDITOR` (requisito novo). Recomendação: (a), porque nenhum requisito pede o recorte e o inventário não tem dado pessoal (011/R4.2).
- (revisão de 24/11/2026, agente; aguarda o dono) Tela de relatórios. A spec 012 não tem tela para pedir e baixar os relatórios desta spec (a exportação da 012, Grupo-DF15, é outra). Recomendação: demonstrar pela API (`/docs` em dev, ou um script), sem tela nova nesta spec; uma tela seria emenda da 012.

## Decisões do G1 (Rafael, 24/11/2026)
- Demonstração pela API (`/docs` em dev, ou um script), sem tela nova nesta spec.
- A validação numa conta AWS real é opcional e depende de haver conta; sem ela, a evidência é a R2.1 com moto, a R2.9 e o documento da T7.
- A criptografia no SeaweedFS é conferida na primeira hora da T8; se faltar, a alternativa volta para decisão antes de seguir.
- O ADR-0005 passa a `Aceito`.
- As recomendações de 09/11/2026 (SeaweedFS no compose, guarda de 90 dias, assinatura ES256 com chave própria e chaves públicas em JWK) entram no design e são confirmadas no G2.

## Revisão de 24/11/2026: checklist da disciplina
- Quem e por quê: agente, a pedido do Rafael; G1 aprovado pelo Rafael no mesmo dia (seção acima). Comparação dos itens de exportação do checklist de acompanhamento acadêmico (`docs/requisitos-iam.docx`, § 4, fora do Git nesta data) com os critérios desta spec.
- O checklist marca como concluídos itens que ainda não têm código. A situação real está em `docs/REQUISITOS_EVIDENCIAS.md` (linha "Exportação para S3"): nada desta spec foi implementado.
- Status sem mudança: o agente não aprova. Design e tarefas não foram reescritos antes do G1 (`/spec-design`, passo 1); os ajustes que os critérios novos pedem estão no fim de cada arquivo.
- Critério existente que mudou: a R3.2 passou de "307 para a URL" para "200 com a URL". Com 307, o download pelo navegador não funciona:
  - o front-end guarda o access token em memória (design da 012) e só o envia por `fetch`, no cabeçalho `Authorization`;
  - um link comum não leva o token;
  - o `fetch` que segue o 307 até o armazenamento, noutro endereço, exige CORS no armazenamento e traz o arquivo inteiro para a memória da página.

  Com a URL no corpo, quem pede (front-end, `/docs` ou script) abre a URL e o navegador baixa direto. O ADR-0005 continua valendo ("download só por URL pré-assinada de 5 minutos").

| Item do checklist | Critérios | Situação na spec |
|---|---|---|
| Geração de relatórios | R1 | coberto |
| Exportação em CSV e XLSX | R1.2, R4 | coberto |
| Armazenamento compatível com S3 | R2, **R6.1** | faltava o armazenamento no compose |
| URLs pré-assinadas para download | **R3.2** (revisto), **R3.6** | revisto |
| Permissões de exportação e download | R1.1, R1.4, R3.2, R3.3 | coberto |
| Checksum SHA-256 | R2.3, **R2.8** | faltava conferir o que o armazenamento gravou |
| Testes automatizados | design § Estratégia de testes | coberto |
| Geração e download dentro da rede Docker | **R6.3** | faltava |
| Download pelo navegador ou pelo host | **R3.2** (revisto), **R3.6**, **R6.2** | faltava: nada pedia URL acessível fora da rede interna, e o 307 não funciona no navegador |
| Autenticação S3 em produção | R2.1, R2.2, **R2.9** | a R2.9 torna a regra de prod verificável sem conta AWS; a validação numa conta real é pergunta em aberto |
| Confirmação da criptografia SSE | R2.3, **R2.8** | faltava: a R2.3 só pedia enviar o cabeçalho |
| Fora do checklist: assinatura digital (disciplina de Criptografia) | R5 | sem design nem tarefa (pergunta de 09/11/2026) |
