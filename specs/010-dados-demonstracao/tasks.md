# 010 · Dados de demonstração · Tarefas

- Status: Rascunho
- Depende de: 006, 007

- [ ] T1. Arquivos YAML de demonstração (Saúde Mental + casos especiais + pendências)
  - Requisitos: R1.2, R1.3, R1.5
  - Pronto quando: `tests/unit/seeds/test_yaml_valido.py` passa
- [ ] T2. Comando `sgs-admin seed demo` idempotente com usuários por papel
  - Requisitos: R1.1, R1.4, R1.6
  - Pronto quando: `tests/integration/seeds/test_seed_demo.py` passa
- [ ] T3. Conversor da planilha de rede com relatório de rejeitos
  - Requisitos: R2.1, R2.2
  - Pronto quando: `tests/unit/seeds/test_classificador_planilha.py` passa
