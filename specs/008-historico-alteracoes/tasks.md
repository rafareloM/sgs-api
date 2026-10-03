# 008 · Histórico de alterações · Tarefas

- Status: Rascunho
- Depende de: 001, 003, 006

- [ ] T1. Índices e consulta paginada com filtros
  - Requisitos: R1.1, R1.3, R2.1
  - Pronto quando: `tests/integration/audit/test_consulta_eventos.py` passa
- [ ] T2. Histórico da unidade com rótulos, nomes de referência, fuso e escopo
  - Requisitos: R1.1, R1.2, R1.4
  - Pronto quando: `tests/integration/audit/test_historico_unidade.py` passa
- [ ] T3. Trilha geral com separação de eventos de acesso e mascaramento
  - Requisitos: R2.1–R2.3, R3.2
  - Pronto quando: `tests/integration/audit/test_trilha_geral.py` passa
- [ ] T4. Verificação de integridade da cadeia
  - Requisitos: R3.1
  - Pronto quando: `tests/integration/audit/test_verificar_cadeia.py` passa
- [ ] T5. Particionamento mensal e comando de manutenção
  - Requisitos: R4.1
  - Pronto quando: `tests/integration/audit/test_particoes.py` passa
