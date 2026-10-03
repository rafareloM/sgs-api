# 003 · RBAC com escopo · Tarefas

- Status: Rascunho
- Depende de: 002

- [ ] T1. Migração `0003_access` com seed da matriz de papéis e permissões
  - Requisitos: R1.1, R1.2, R1.3
  - Pronto quando: `tests/integration/access/test_seed_matriz.py` passa
- [ ] T2. Função de domínio `pode()` e tipos de escopo
  - Requisitos: R4.2, R4.3
  - Pronto quando: `tests/unit/access/test_pode_matriz.py` (parametrizado pela matriz) passa
- [ ] T3. Resolução de permissões efetivas com cache e `authz_version`
  - Requisitos: R4.5
  - Pronto quando: `tests/integration/access/test_permissoes_efetivas.py` passa
- [ ] T4. Dependência `require()` e `scope_filter()`
  - Requisitos: R4.1, R4.3, R4.4, R4.6
  - Pronto quando: `tests/integration/access/test_require.py` passa
- [ ] T5. Teste de arquitetura de rotas protegidas
  - Requisitos: R4.1
  - Pronto quando: `tests/architecture/test_rotas_protegidas.py` passa
- [ ] T6. `GET /me`
  - Requisitos: R5.1
  - Pronto quando: `tests/integration/access/test_me.py` passa
- [ ] T7. Rotas de administração de atribuições com validação de escopo e auditoria
  - Requisitos: R2.1–R2.5
  - Pronto quando: `tests/integration/access/test_admin_atribuicoes.py` passa
- [ ] T8. Mapeamentos grupo→papel e recálculo de atribuições derivadas
  - Requisitos: R3.1–R3.3
  - Pronto quando: `tests/integration/access/test_mapeamento_grupos.py` passa
