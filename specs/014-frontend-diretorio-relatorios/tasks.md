# 014 · Front-end do diretório e dos relatórios · Tarefas

- Status: **Aprovado (G3: Rafael (rafareloM), dono, em 26/11/2026)**. Registro do agente por autorização expressa dada na sessão de trabalho. Pela tabela de `steering/sdd-workflow.md`, o G3 é só do dono.
- Requisitos e design: `Aprovado` (G1 e G2 do Rafael em 26/11/2026).
- Depende de: 012 (front), 004 e 005 na `main` (`271d042`). Nenhuma dependência de backend.

Cada tarefa é pequena (até ~300 linhas de diff), testável e cita os requisitos que cobre. Só se marca `[x]` quando o teste citado passa e o `make check` está verde. As suítes de `tests/e2e_front/` são `slow`: a tarefa registra a execução delas no commit.

Entrega (26/11/2026): T1 `c398b02`, T5 `63be088`, T2 `bf99d6d`, T3 `2d92813`, T4 `bf5c75d`, integração `0819e43`, T6 no commit da documentação. `make check` verde em `0819e43` (1897 passed); `tests/e2e_front` completo na ordem normal: 140 passed até `test_relatorios.py` inclusive, com a correção do SeaweedFS (design § Riscos); as 3 falhas de `test_aparencia.py` (largura do login) já ocorrem em `271d042` (`main`) e não são desta spec; a execução foi interrompida por falta de memória da VM em `test_servicos.py`, que não muda nesta spec e passou na primeira execução completa.

Ordem: T1 → (T2 ∥ T4 ∥ T5) → T3 → T6. T2, T4 e T5 mexem em arquivos diferentes e podem correr em paralelo.

- [x] T1. Base: menu, rotas, telas vazias e ambiente E2E
  - Requisitos: R1.1, R4.1, R6.1 (parte)
  - Arquivos: `js/perms.js` (itens Relatórios e Diretório), `js/main.js` (rotas `relatorios`, `diretorio`, `diretorio/:aba`), `js/views/relatorios.js`, `js/views/diretorio.js` e `js/views/grupos.js` (novos, com o cabeçalho, as abas e "Tela em implantação"), `js/atualizacao.js` (novo, `atualizarEnquanto`), `tests/e2e_front/conftest.py` (`ldap s3 s3-init` e `SGS_PUBLIC_S3_URL`), `tests/e2e_front/test_perfis.py` (quadros do Admin TI e de `relatorio:export`).
  - Pronto quando: `tests/e2e_front/test_perfis.py` passa com os quadros novos (menu do Admin TI com Diretório e início em `#/diretorio`; Relatórios no menu de Gestor de Dados, Coordenação, Diretoria e Auditoria) e `tests/e2e_front/test_diretorio.py::test_abas_conforme_permissao` passa.

- [x] T2. Relatórios: formulário, lista e atualização
  - Requisitos: R1.2 a R1.7, R2.1, R2.2, R2.5, R6.1
  - Arquivos: `js/views/relatorios.js`, `tests/e2e_front/test_relatorios.py` (novo).
  - Pronto quando: `tests/e2e_front/test_relatorios.py` passa com `test_diretoria_nao_ve_trilha`, `test_pedido_de_inventario_conclui_sem_clique`, `test_periodo_longo_mostra_erro_no_campo`, `test_atualizacao_para_ao_sair`, `test_exportacao_desligada_503` e `test_falhou_permite_pedir_de_novo`.

- [x] T3. Relatórios: baixar e integridade
  - Requisitos: R2.3, R2.4, R3.1 a R3.3
  - Depende de: T2.
  - Arquivos: `js/views/relatorios.js`, `tests/e2e_front/test_relatorios.py`.
  - Pronto quando: `test_baixar_entrega_arquivo_com_o_sha256_da_integridade`, `test_copiar_integridade_json` e `test_download_409_vira_aviso` passam.

- [x] T4. Diretório: execuções e sincronização
  - Requisitos: R4.2 a R4.6, R6.1
  - Arquivos: `js/views/diretorio.js`, `tests/e2e_front/test_diretorio.py`.
  - Pronto quando: `test_sincronizar_agora_conclui_e_mostra_contagens`, `test_detalhe_da_execucao`, `test_sincronizacao_em_andamento_409_vira_aviso` e `test_ldap_desligado_503` passam.

- [x] T5. Diretório: grupos e mapeamentos
  - Requisitos: R5.1 a R5.5, R6.1
  - Arquivos: `js/views/grupos.js`, `tests/e2e_front/test_diretorio.py`.
  - Pronto quando: `test_grupos_listados_e_buscados`, `test_mapear_grupo_aparece_com_o_nome`, `test_escopo_invalido_mostra_erro_no_campo`, `test_segregacao_de_funcoes_mostra_mensagem_da_api` e `test_remover_mapeamento` passam.

- [x] T6. Documentação e nota de referência
  - Requisitos: rastreabilidade (`steering/sdd-workflow.md`)
  - Arquivos: nota de referência em `specs/012-frontend/design.md` (como a 004/T10), linha da 014 em `specs/README.md`, passos pela tela em `docs/operacao/demo-relatorios.md` e `docs/operacao/demo-diretorio.md`.
  - Pronto quando: `make check` verde e a revisão por agente (`/spec-revisar`) sem bloqueio.
