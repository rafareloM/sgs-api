# ADR-0005: Exportação de relatórios para S3 com STS

- Status: Proposto
- Data: 2026-10-03
- Requisitos relacionados: RF-07 (parcial), RNF-05, RS-03, RS-04, requisito obrigatório de exportação para nuvem

## Contexto
O requisito obrigatório pede exportar relatórios para armazenamento em nuvem usando mecanismos avançados de autenticação. A Entrega Final deixou "relatórios avançados e múltiplos formatos" fora do MVP. MinIO e LocalStack deixaram de ter imagens gratuitas utilizáveis em 2025/2026.

## Decisão
- Dois relatórios simples: inventário de unidades e trilha de auditoria, em CSV e XLSX, gerados de forma assíncrona e respeitando o escopo de quem pediu.
- Upload com boto3 usando credenciais temporárias de STS `AssumeRole` (ExternalId, sessão identificada pelo usuário), SigV4, `SSE-KMS`, checksum SHA-256, bucket privado com política que exige TLS.
- Download só por URL pré-assinada de 5 minutos.
- Desenvolvimento com SeaweedFS (S3 compatível) e testes com moto.

## Consequências
- Atende o requisito sem reabrir o escopo de relatórios avançados (registrar como decisão justificada no relatório final).
- Exige uma conta AWS (ou compatível) para a demonstração em nuvem; sem ela, a demo usa SeaweedFS com o mesmo código.

## Alternativas consideradas
- Chave de acesso fixa (access key) no `.env`: simples, mas é exatamente o que o requisito de "autenticação avançada" quer evitar.
- Google Cloud Storage / Azure Blob: possíveis via a mesma porta `ObjectStoragePort`, mas S3 é o exemplo citado.
