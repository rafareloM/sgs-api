# 010 · Dados de demonstração · Requisitos

- Status: Rascunho
- Rastreia: pendência 6 dos Requisitos Esperados ("origem da massa de dados de teste", prazo 07/11); critério 6.1 "sobe em outra máquina"; testes de usabilidade de 24/10

## Contexto
Sem dados, a demonstração fica vazia e o dashboard não mostra nada. O cliente forneceu um modelo da planilha de rede; o escopo temático do grupo é Saúde Mental (CAPS, CECON, SIM).

## Fora do escopo
- Importação genérica de CSV/Excel pela interface (evolução, RNF-05).
- Dados reais de pessoas.

## Histórias e critérios

### R1. Carga de demonstração
- R1.1 QUANDO alguém executa `sgs-admin seed demo`, o sistema DEVE carregar referências, unidades, equipamentos e serviços de demonstração de forma idempotente (rodar duas vezes não duplica).
- R1.2 A massa DEVE cobrir todos os distritos, os tipos de Saúde Mental (CAPS II, CAPS AD, CAPS i, CECON, SIM) e os casos especiais citados pelo cliente: unidade com dois equipamentos, equipamento sem unidade, serviço solto, CAPS com Farmácia, unidade sem CNES.
- R1.3 A massa DEVE incluir unidades com pendências de validação, para o dashboard mostrar qualidade.
- R1.4 O sistema DEVE criar um usuário de demonstração por papel, com 2FA desativado apenas quando `APP_ENV=dev`.
- R1.5 Os nomes de pessoas DEVEM ser fictícios; nomes e CNES de unidades podem ser públicos.
- R1.6 SE `APP_ENV=prod`, ENTÃO o comando DEVE recusar executar.

### R2. Conversão da planilha do cliente
- R2.1 ONDE o grupo tiver a planilha REDE_SAUDE_RECIFE_GEO, um script DEVE convertê-la para o formato de seed, separando unidades, equipamentos e serviços pelas convenções descritas pelo cliente (colunas "É EQUIPAMENTO DE SAÚDE?", "UNIDADE", "TIPO SERVIÇO", "UNIDADE POSSUI FARMÁCIA DA FAMÍLIA").
- R2.2 O script DEVE gerar um relatório das linhas que não conseguiu classificar.

## Perguntas em aberto
- O grupo pode usar a planilha do cliente no repositório, ou ela deve ficar fora do Git?
