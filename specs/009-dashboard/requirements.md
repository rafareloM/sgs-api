# 009 · Dashboard básico · Requisitos

- Status: Rascunho
- Rastreia: RF-06; critério 6.1 "dashboard exibe indicadores que refletem os dados realmente cadastrados"

## Contexto
O cliente já tem dashboards e disse que este serve para conferir os dados inseridos (reunião de 18/09). Por isso o escopo é mínimo: agregados corretos e rápidos, sem gráficos no backend.

## Fora do escopo
- Séries históricas, metas, exportação do dashboard, mapa GIS.

## Histórias e critérios

### R1. Resumo da rede
- R1.1 QUANDO um usuário com `dashboard:read` chama `GET /dashboard/resumo`, o sistema DEVE responder total de unidades por status, distribuição por tipo, por área técnica e por distrito.
- R1.2 O sistema DEVE responder quantidade de unidades com pendências de validação e o total de pendências.
- R1.3 O sistema DEVE responder quantidade de unidades sem CNES e de serviços fora do CNES.
- R1.4 O sistema DEVE responder as alterações dos últimos 7 e 30 dias e as 10 unidades alteradas mais recentemente.
- R1.5 O sistema DEVE calcular os números a partir da base atual, considerando o escopo de leitura do usuário.
- R1.6 O sistema DEVE aceitar filtros por distrito e área técnica.
- R1.7 O sistema DEVE responder em menos de 1 s com 1.000 unidades.

## Perguntas em aberto
- Quais indicadores o Sérgio usa para conferir os dados? (validar na próxima reunião)
