# 005 · Exportação de relatórios para S3 · Requisitos

- Status: Rascunho
- Rastreia: RF-07 (parcial), RNF-05, RS-03, RS-04, RS-05, requisito obrigatório "exportação de relatórios para armazenamento em nuvem com mecanismos de autenticação avançados"

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

### R3. Consultar e baixar
- R3.1 QUANDO o solicitante consulta `GET /relatorios/{id}`, o sistema DEVE devolver o status.
- R3.2 QUANDO um usuário com `relatorio:download` pede `GET /relatorios/{id}/download` de um relatório concluído, o sistema DEVE responder 307 para uma URL pré-assinada válida por 5 minutos.
- R3.3 O sistema DEVE permitir o download apenas ao solicitante ou a quem tenha escopo igual ou maior que o do relatório.
- R3.4 O sistema DEVE auditar `relatorio.baixado`.
- R3.5 QUANDO o usuário lista `GET /relatorios`, o sistema DEVE mostrar os pedidos dele (ou todos, para `GESTOR_DADOS`).

### R4. Conteúdo
- R4.1 O CSV DEVE ser UTF-8 com BOM e separador `;`, para abrir corretamente no Excel em português.
- R4.2 O sistema DEVE neutralizar valores iniciados por `=`, `+`, `-` ou `@` (prevenção de injeção de fórmula em CSV/XLSX).
- R4.3 A trilha de auditoria exportada NÃO DEVE conter valores marcados como sensíveis.

## Perguntas em aberto
- O grupo terá uma conta AWS para a demonstração (AWS Educate/Academy)? Se não, a demo usa SeaweedFS.
- Por quanto tempo os relatórios ficam no bucket? (padrão: regra de ciclo de vida de 90 dias)
