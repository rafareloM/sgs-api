# ADR-0001: FastAPI/Python como backend

- Status: Proposto (aguarda confirmação do grupo)
- Data: 2026-10-03
- Requisitos relacionados: RF-03, RS-08, pendência 1 dos Requisitos Esperados

## Contexto
Os documentos do grupo citam duas stacks: a Atividade 3 lista FastAPI no texto e NodeJS/TypeScript na tabela; a Atividade 5 registra Node.js como "decisão final". O pedido atual do grupo define FastAPI em Python. O critério 6.2 da Entrega Final exige que o documento de arquitetura descreva a stack efetivamente usada.

## Decisão
O backend será construído em Python 3.13 com FastAPI, SQLAlchemy 2 (async), Alembic e PostgreSQL. Este ADR substitui a linha "API / Backend: Node.js" do Documento de Arquitetura da Atividade 5.

## Consequências
- O Documento de Arquitetura (Atividade 5, §2 e §5) precisa ser atualizado para FastAPI antes da próxima entrega, senão o critério 6.2 falha.
- Validação de entrada e documentação OpenAPI saem prontas do framework (RF-03, RS-08).
- O ecossistema Python tem bibliotecas maduras para LDAP (ldap3), OIDC (Authlib) e S3 (boto3), que são os três requisitos obrigatórios desta etapa.

## Alternativas consideradas
- Node.js/TypeScript (NestJS ou Express): viável, mas contraria a definição atual do grupo.
- Django REST Framework: mais pesado para uma API sem páginas server-side.
