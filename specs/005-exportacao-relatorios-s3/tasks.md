# 005 · Exportação de relatórios para S3 · Tarefas

- Status: **Aprovado (G3: Rafael (rafareloM), dono, em 24/11/2026)**. Registro do agente por autorização expressa dada na sessão de trabalho. Pela tabela de `steering/sdd-workflow.md`, o G3 é só do dono. Execução em três frentes, com guias em `docs/implementacao/`.
- Requisitos e design: `Aprovado` (G1 e G2 do Rafael em 24/11/2026).
- Depende de: 001, 003 (escopo de leitura), 006 e 011 (`vw_unit_inventory`, `vw_unit_history`), 004/T8 (peças compartilhadas do compose, na T8).
- Histórico: lista de 03/10/2026 (T1 a T8); notas de 09/11/2026 (T9 da R5 proposta) e 24/11/2026; reescrita por agente em 24/11/2026 com `/spec-tarefas`, depois do G2. A reescrita aplica as notas, inclui a R5 e divide o trabalho das specs 004 e 005 em três frentes simultâneas (Decisões do G2). As tarefas antigas mantêm o número quando o conteúdo é o mesmo; as novas vêm depois da T9.

Cada tarefa é pequena (até ~300 linhas de diff), testável e cita os requisitos que cobre. Só se marca `[x]` quando o teste citado passa e o `make check` está verde. Arquivos de teste citados aqui ainda não existem e nascem na tarefa, menos `tests/unit/core/test_config.py`, que só ganha testes.

## Frentes de trabalho (specs 004 e 005)
O mesmo quadro está em `specs/004-diretorio-ldap-oidc/tasks.md`, que traz também as regras de integração (ramos, migrações, arquivos compartilhados). As estimativas são em horas de trabalho focado.

| Frente | Ordem | Estimativa |
|---|---|---|
| Base (antes de dividir) | 004/T0 = 005/T0 (uma tarefa só, um commit) | 2 h |
| **A · Diretório LDAP** | 003/T8 (porte) → 004/T1 → T2 → T11 → T12 → T3 → T5 → T4 → T9 → 005/T7 | 35 a 50 h |
| **B · OIDC e laboratório** | 004/T8 → T13 → 005/T9 → 004/T6 → T10 → T7 → T14 | 30 a 48 h |
| **C · Relatórios** | 005/T10 → T12 → T1 → T2 → T11 → T3 → T4 → T5 → T6 → T8 | 35 a 52 h |

Esta spec tem tarefas em três frentes:
- a 005/T7 (documento da AWS) está na frente A;
- a 005/T9 (assinatura) está na frente B, para equilibrar a carga;
- o resto está na C.

Pontos de encontro desta spec:
- a T5 espera a T9 (frente B);
- a T8 espera a 004/T8 (frente B).

## Dependências
| Tarefa | Frente | Depende de | Por quê |
|---|---|---|---|
| T0 | base | — | dependências e erro 503 usados pelas duas specs |
| T10 | C | — | confere o SeaweedFS antes de investir no resto (G1) |
| T12 | C | — | funções puras do domínio |
| T1 | C | T0 | tabela e repositório |
| T2 | C | T0 | `openpyxl` |
| T11 | C | T1 | as consultas ficam no módulo que a T1 cria |
| T3 | C | T0 | `boto3` e `moto` |
| T4 | C | T0 | campos de configuração |
| T9 | B | T0 | chaves e rota pública; não depende do resto |
| T5 | C | T1, T2, T3, T9, T11 | junta geração, assinatura e envio |
| T6 | C | T4, T5, T12 | rotas e composição na raiz |
| T7 | A | — | documento |
| T8 | C | T6, T10, 004/T8 | compose com as peças compartilhadas da 004 |

## Tarefas
- [x] T0. Base comum das specs 004 e 005. É a mesma tarefa que a 004/T0, num commit `(004/T0, 005/T0)`; a descrição completa está em `specs/004-diretorio-ldap-oidc/tasks.md`.
  - Concluída em 24/11/2026 (`make check` verde). Prova: `tests/unit/core/test_errors.py::test_service_unavailable_responde_503`
  - Frente: base
  - Requisitos: — (infraestrutura das tarefas seguintes)
  - Pronto quando: `uv.lock` travado, `tests/unit/core/test_errors.py::test_service_unavailable_responde_503` passa e o `make check` está verde
- [x] T10. Conferência antecipada do SeaweedFS, sem mudar o repositório
  - Concluída em 26/11/2026 (`make check` verde). Prova: registro em `design.md` § Riscos, "Conferência antecipada do SeaweedFS"
  - Frente: C
  - Faz:
    - sobe a imagem `chrislusf/seaweedfs` na tag que a T8 vai fixar, com o S3 em HTTPS (certificado de teste);
    - envia um objeto com `ServerSideEncryption=AES256` e `ChecksumSHA256` pelo `boto3`;
    - confere o que a resposta informa e as opções de TLS do `weed server`.

    Faz mais cedo a conferência que o G1 pôs na primeira hora da T8; a T8 confere de novo, já no compose.
  - Bloqueada por: —
  - Requisitos: R2.8, R6.1 (verificação de viabilidade)
  - Pronto quando: o resultado (tag, comandos, resposta) está registrado no design § Riscos. Se a SSE não vier confirmada, a frente C para e a decisão volta ao dono (G1).
- [x] T12. Filtros e comparação de escopo (domínio puro)
  - Concluída em 26/11/2026 (`make check` verde). Prova: `tests/unit/reports/test_filtros.py`, `tests/unit/reports/test_escopo_cobre.py`
  - Frente: C
  - Faz:
    - modelos dos filtros por tipo, com o período da trilha de até 366 dias;
    - `escopo_cobre(maior, menor)`, com a comparação conservadora.
  - Bloqueada por: —
  - Requisitos: R1.2, R1.5, R3.3
  - Pronto quando: `tests/unit/reports/test_filtros.py` e `tests/unit/reports/test_escopo_cobre.py` passam
- [x] T1. Migração `0005_relatorios` e repositório de pedidos
  - Concluída em 26/11/2026 (`make check` verde). Prova: `tests/integration/reports/test_report_jobs.py`
  - Frente: C
  - Faz:
    - `report_jobs` com versão do objeto, colunas de assinatura, `CHECK` de coerência e índices;
    - repositório em SQLAlchemy Core: criar, marcar `gerando` só se `pendente`, concluir, falhar, interrompidos, listar;
    - `modelo-dados.md` § 4;
    - regra do `down_revision` em `specs/004-diretorio-ldap-oidc/tasks.md` § Frentes.
  - Bloqueada por: T0
  - Requisitos: R1.1, R2.5, R5.1
  - Pronto quando: `tests/integration/reports/test_report_jobs.py` passa
- [x] T2. Geradores CSV e XLSX
  - Concluída em 26/11/2026 (`make check` verde). Prova: `tests/unit/reports/test_generators.py::test_xlsx_nenhuma_celula_e_formula_e_texto_perigoso_ganha_aspa`, `::test_csv_utf8_com_bom_ponto_e_virgula_e_crlf` e `::test_sha256_e_tamanho_calculados_durante_a_escrita_conferem_com_o_arquivo` (arquivo inteiro passa)
  - Frente: C
  - Faz:
    - CSV: UTF-8 com BOM, `;` e `\r\n`;
    - neutralização das células de texto;
    - XLSX em `write_only` com célula de texto explícita;
    - SHA-256 calculado durante a escrita;
    - limite de linhas.
  - Bloqueada por: T0
  - Requisitos: R1.2, R4.1, R4.2, R4.3
  - Pronto quando: `tests/unit/reports/test_generators.py` passa
- [x] T11. Consultas dos relatórios em SQL explícito
  - Concluída em 26/11/2026 (`make check` verde). Prova: `tests/integration/reports/test_consultas_relatorio.py`
  - Frente: C
  - Faz:
    - `inventario_unidades.sql` (`vw_unit_inventory`), `trilha_auditoria_global.sql` e `trilha_auditoria_escopo.sql` (`vw_unit_history`), com cabeçalho (ADR-0009);
    - fragmento de escopo de `src/core/escopo.py`;
    - leitura por cursor do servidor em `REPEATABLE READ, READ ONLY`;
    - a trilha fica sem eventos de acesso e sem `metadata`, IP, User-Agent e sessão.
  - Bloqueada por: T1
  - Requisitos: R1.3, R4.3
  - Pronto quando: `tests/integration/reports/test_consultas_relatorio.py` passa
- [x] T3. Armazenamento S3: porta, adaptador e conferência da gravação
  - Concluída em 26/11/2026 (`make check` verde). Prova: `tests/unit/reports/test_conferencia.py`, `tests/integration/reports/test_s3_adapter.py`
  - Frente: C
  - Faz:
    - `ArmazenamentoDeObjetos`, `ObjetoGravado` e `conferir_gravacao` no domínio;
    - `s3_storage.py`: `AssumeRole` por operação (`sgs-{id}`, `ExternalId`, 900 s), cliente interno e cliente público, `Config` com checksum `when_required`, SSE e `ChecksumSHA256`, remoção pela versão, URL de 300 s com `Content-Disposition`, chamadas em *thread*.
  - Bloqueada por: T0
  - Requisitos: R2.1, R2.3, R2.4, R2.7, R2.8, R3.2, R3.6
  - Pronto quando: `tests/unit/reports/test_conferencia.py` e `tests/integration/reports/test_s3_adapter.py` (`moto`) passam
- [x] T4. Configuração S3 e recusas em `prod`
  - Concluída em 26/11/2026 (`make check` verde). Prova: `tests/unit/core/test_config.py::test_prod_recusa_iniciar_sem_bucket_papel_external_id_ou_chave_kms`, `::test_prod_recusa_iniciar_com_chave_fixa`, `::test_s3_recusa_endereco_sem_https`, `::test_exportacao_fica_desligada_sem_s3_bucket`
  - Frente: C
  - Faz: campos `S3_*` e `REPORT_RETENTION_DAYS` em `Settings` (`_s3_problems`):
    - só `https://`;
    - em `prod`, papel, `ExternalId` e ARN de KMS obrigatórios e `aws:kms` exigido;
    - chave fixa (`S3_*` e `AWS_*`) recusada em `prod`;
    - exportação desligada sem `S3_BUCKET`.
  - Bloqueada por: T0
  - Requisitos: R2.2, R2.7, R2.9
  - Pronto quando: os testes S3 de `tests/unit/core/test_config.py` passam
- [x] T9. Assinatura dos relatórios e chaves públicas
  - Concluída em 25/11/2026 (`make check` verde). Prova: `tests/unit/reports/test_assinatura.py`, `tests/integration/reports/test_chaves_publicas.py`
  - Frente: B
  - Faz:
    - `REPORT_SIGNING_KEYS(_FILE)` em `Settings`: o leitor das chaves JWT, chaves iguais às JWT recusadas, chave de exemplo recusada em `prod`;
    - `AssinadorDeRelatorio` e adaptador ES256 (`Prehashed`, `r‖s` em base64url);
    - `GET /.well-known/relatorios-jwks.json`;
    - `docs/operacao/verificar-relatorio.md`, com a rotação e a verificação fora da API;
    - geração das chaves pelo `src.tools.jwt_keys`, documentada no README.
  - Bloqueada por: T0
  - Requisitos: R5.1, R5.2, R5.4, R5.5
  - Pronto quando: `tests/unit/reports/test_assinatura.py` e `tests/integration/reports/test_chaves_publicas.py` passam
- [ ] T5. Caso de uso da geração e do envio
  - Frente: C
  - Faz:
    - `gerar_relatorio(id)`: `gerando` só se `pendente`, geração no escopo gravado, assinatura, envio com a sessão de quem pediu, conferência e remoção;
    - `concluido` com hash, assinatura e `expires_at`, e `relatorio.exportado`;
    - falha com mensagem genérica e transação própria;
    - interrompidos marcados na subida.
  - Bloqueada por: T1, T2, T3, T9, T11
  - Requisitos: R1.3, R2.5, R2.6, R2.8, R5.1
  - Pronto quando: `tests/integration/reports/test_gerar_relatorio.py` passa
- [ ] T6. Rotas de pedido, consulta, listagem e download
  - Frente: C
  - Faz:
    - `POST /relatorios` com a permissão de dados do tipo e `relatorio.solicitado`;
    - `GET /relatorios` (próprios, ou todos para `GESTOR_DADOS`);
    - `GET /relatorios/{id}` com `integridade`;
    - `GET /relatorios/{id}/download`: 200 `{url, expira_em}`, `no-store`, 403, 404 e 409, e `relatorio.baixado` sem a URL;
    - composição na raiz (`main.py`) e `make openapi`.
  - Bloqueada por: T4, T5, T12
  - Requisitos: R1.1, R1.4, R1.5, R3.1, R3.2, R3.3, R3.4, R3.5, R5.3
  - Pronto quando: `tests/integration/reports/test_report_routes.py` passa, com 401, 403 e 422
- [ ] T7. Documento de exemplo da AWS
  - Frente: A
  - Faz: `docs/architecture/aws-iam-exemplo.md` (design § Ambiente, "AWS real"):
    - bucket privado, versionado, com ciclo de vida de 90 dias;
    - política com TLS e `aws:kms`;
    - papel com `PutObject`, `GetObject` e `DeleteObjectVersion` em `reports/*`;
    - KMS;
    - confiança com `ExternalId`;
    - identidade da execução com `sts:AssumeRole`.
  - Bloqueada por: —
  - Requisitos: R2.1, R2.3
  - Pronto quando: o documento foi revisado por um integrante
- [ ] T8. SeaweedFS no compose e demonstração ponta a ponta
  - Frente: C
  - Primeira hora: conferir de novo, já no compose, a SSE e o TLS vistos na T10.
  - Faz:
    - serviço `s3` com tag fixa, HTTPS pelo `servicos-certs` e `docker/seaweedfs/s3.json`;
    - `s3-init`, que cria o bucket;
    - bloco `s3.localhost` no Caddy;
    - `SGS_PUBLIC_S3_URL`;
    - `S3_*` e o segredo `report_keys` da API no compose;
    - `.env.example` com `https://`;
    - README e `docs/operacao/demo-relatorios.md`.
  - Bloqueada por: T6, T10, 004/T8
  - Requisitos: R2.7, R2.8, R6.1, R6.2, R6.3
  - Pronto quando: `tests/e2e/test_export_s3.py -m slow` passa, conferindo:
    - pedido e envio por HTTPS, com SSE e checksum conferidos;
    - download da URL pelo navegador do host (Playwright, `s3.localhost`);
    - hash e assinatura conferidos com a JWK pública.

## Opcional, se houver conta AWS (G1)
Fica fora da lista acima, porque depende de conta. Se a conta permitir criar papel IAM e chave KMS, uma tarefa de evidência roda o envio numa conta real, com o papel e a chave da T7, e registra o resultado em `docs/operacao/evidencias/` (R2.1, R2.3, R2.9).

## Cobertura dos requisitos
| Requisito | Tarefas |
|---|---|
| R1.1 | T1, T6 |
| R1.2 | T12, T2 |
| R1.3 | T11, T5 |
| R1.4 | T6 |
| R1.5 | T12, T6 |
| R2.1 | T3, T7 |
| R2.2 | T4 |
| R2.3 | T3, T7 |
| R2.4 | T3 |
| R2.5 | T1, T5 |
| R2.6 | T5 |
| R2.7 | T3, T4, T8 |
| R2.8 | T10, T3, T5, T8 |
| R2.9 | T4 |
| R3.1 | T6 |
| R3.2 | T3, T6 |
| R3.3 | T12, T6 |
| R3.4, R3.5 | T6 |
| R3.6 | T3 |
| R4.1, R4.2 | T2 |
| R4.3 | T2, T11 |
| R5.1 | T1, T9, T5 |
| R5.2, R5.4, R5.5 | T9 |
| R5.3 | T6 |
| R6.1 | T10, T8 |
| R6.2, R6.3 | T8 |

Sem cobertura: nenhum.
