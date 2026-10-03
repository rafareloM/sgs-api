---
description: Cria ou atualiza requirements.md de uma spec no formato EARS
argument-hint: <NNN-nome> <descrição do pedido>
---
Crie ou atualize `specs/$1/requirements.md` a partir de `specs/_templates/requirements.md`.

Contexto do pedido: $ARGUMENTS

1. Leia `steering/product.md` e `steering/security.md`.
2. Liste as histórias com papel, ação e benefício, usando os papéis de `steering/product.md`.
3. Escreva critérios EARS numerados (`R1.1`...), cada um testável e sem detalhe de implementação.
4. Inclua critérios negativos (acesso negado, entrada inválida, falha de integração).
5. Rastreie a RF/RNF/RS no cabeçalho. Preencha "Fora do escopo" e "Perguntas em aberto".
6. Deixe `Status: Rascunho`. Não escreva design nem código.
7. Ao final, resuma as perguntas em aberto para o dono humano.
