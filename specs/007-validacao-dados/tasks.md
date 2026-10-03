# 007 · Validação de dados · Tarefas

- Status: Rascunho
- Depende de: 006

- [ ] T1. Normalizadores e validadores de formato (CNES, CEP, telefone, coordenadas, horário) nos schemas
  - Requisitos: R1.3, R1.6
  - Pronto quando: `tests/unit/registry/test_formatos.py` passa
- [ ] T2. Validador de domínio com regras de coerência e catálogo de mensagens
  - Requisitos: R1.4, R1.5
  - Pronto quando: `tests/unit/registry/test_regras_coerencia.py` passa
- [ ] T3. Integração do validador nos casos de uso de gravação (422 sem gravar)
  - Requisitos: R1.1, R1.2
  - Pronto quando: `tests/integration/registry/test_dado_invalido_nao_grava.py` passa
- [ ] T4. Migração e CRUD de regras configuráveis com auditoria
  - Requisitos: R2.1–R2.4
  - Pronto quando: `tests/integration/registry/test_regras_configuraveis.py` passa
- [ ] T5. Simulação de validação
  - Requisitos: R2.5
  - Pronto quando: `tests/integration/registry/test_simular_validacao.py` passa
- [ ] T6. Pendências por alerta e revalidação da base
  - Requisitos: R3.1–R3.3
  - Pronto quando: `tests/integration/registry/test_pendencias.py` passa
