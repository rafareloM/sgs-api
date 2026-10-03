# 005 · Exportação de relatórios para S3 · Tarefas

- Status: Rascunho
- Depende de: 001, 003 (escopo de leitura). O gerador de inventário depende de `health_units` (spec 006); até lá, usa o stub da spec 003.

- [ ] T1. Migração `report_jobs` e repositório
  - Requisitos: R1.1, R2.5
  - Pronto quando: `tests/integration/reports/test_report_jobs.py` passa
- [ ] T2. Geradores CSV/XLSX com escopo, BOM e neutralização de fórmula
  - Requisitos: R1.2, R1.3, R4.1–R4.3
  - Pronto quando: `tests/unit/reports/test_generators.py` passa
- [ ] T3. `ObjectStoragePort` + adaptador boto3 com STS AssumeRole, SSE e checksum
  - Requisitos: R2.1–R2.4, R2.7
  - Pronto quando: `tests/integration/reports/test_s3_adapter.py` (moto) passa
- [ ] T4. Validação de configuração de produção (sem chave fixa)
  - Requisitos: R2.2
  - Pronto quando: `tests/unit/core/test_config.py::test_prod_exige_assume_role` passa
- [ ] T5. Caso de uso assíncrono de geração e envio com tratamento de falha
  - Requisitos: R2.5, R2.6
  - Pronto quando: `tests/integration/reports/test_gerar_relatorio.py` passa
- [ ] T6. Rotas de pedido, consulta, listagem e download pré-assinado com auditoria
  - Requisitos: R1.1, R1.4, R1.5, R3.1–R3.5
  - Pronto quando: `tests/integration/reports/test_report_routes.py` passa
- [ ] T7. Documento com exemplo de bucket policy, papel IAM e chave KMS
  - Requisitos: R2.1, R2.3
  - Pronto quando: `docs/architecture/aws-iam-exemplo.md` revisado por um integrante
- [ ] T8. SeaweedFS no compose e teste ponta a ponta
  - Requisitos: R2.7
  - Pronto quando: `tests/e2e/test_export_s3.py -m slow` passa
