# ADR-0002: Monólito modular com camadas

- Status: Proposto
- Data: 2026-10-03
- Requisitos relacionados: RNF-06, pedido do cliente por "algo modular"

## Contexto
Cerca de 250 unidades, seis integrantes, prazo até dezembro de 2026. O cliente pediu uma solução modular para evoluir (infraestrutura das unidades, CNES). A Atividade 3 já descartou filas e múltiplos serviços.

## Decisão
Um único serviço FastAPI dividido em módulos (`identity`, `access`, `registry`, `audit`, `reports`, `dashboard`), cada um com as camadas `api`, `application`, `domain` e `infrastructure`. Integrações externas (LDAP, OIDC, S3, CNES) ficam atrás de portas (interfaces) no domínio. As regras de importação são verificadas pelo import-linter no CI.

## Consequências
- Um deploy, um banco, transações simples (alteração e auditoria na mesma transação).
- Módulos podem ser extraídos depois, porque já se comunicam por interfaces.
- Exige disciplina de fronteiras, garantida por ferramenta e não por convenção.

## Alternativas consideradas
- Microsserviços: complexidade operacional sem ganho no volume atual.
- Monólito sem camadas: mais rápido no começo, difícil de testar e evoluir.
