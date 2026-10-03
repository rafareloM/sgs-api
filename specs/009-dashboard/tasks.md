# 009 · Dashboard básico · Tarefas

- Status: Rascunho
- Depende de: 006, 007, 008

- [ ] T1. Consultas agregadas com escopo e filtros
  - Requisitos: R1.1–R1.6
  - Pronto quando: `tests/integration/dashboard/test_resumo.py` passa
- [ ] T2. Cache com invalidação por versão
  - Requisitos: R1.7
  - Pronto quando: `tests/unit/dashboard/test_cache.py` passa
- [ ] T3. Teste de desempenho
  - Requisitos: R1.7
  - Pronto quando: `tests/e2e/test_dashboard_desempenho.py -m slow` passa
