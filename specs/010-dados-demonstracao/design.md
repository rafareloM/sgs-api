# 010 · Dados de demonstração · Design

- Status: Rascunho

## Formato
Arquivos YAML em `seeds/demo/` (`referencias.yaml`, `unidades.yaml`, `usuarios.yaml`), validados pelos mesmos schemas Pydantic da API. A carga passa pelos casos de uso (spec 006), garantindo que dados de seed respeitam as regras de validação e geram auditoria com o ator `sistema-seed`.

## Idempotência
Chave natural: CNES quando houver; senão (`district`, `name_normalized`). Upsert por chave.

## Comando
`sgs-admin seed demo [--reset]` (Typer). `--reset` só em `dev`/`test`. O compose de `dev` roda o seed após as migrações.

## Conversor da planilha
`scripts/converter_planilha_rede.py` (openpyxl) lê a aba `REDE_SAUDE_RECIFE_GEO`, classifica cada linha com regras explícitas e testáveis, grava YAML e um CSV de rejeitos. A planilha original fica fora do repositório (`.gitignore`), a menos que o cliente autorize.

## Estratégia de testes
- Integração: seed duas vezes → mesmas contagens; casos especiais presentes; recusa em `prod`.
- Unidade: classificador de linhas da planilha com linhas de exemplo sintéticas.
