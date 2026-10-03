# 005 · Exportação de relatórios para S3 · Design

- Status: Rascunho

## Portas
```python
class ObjectStoragePort(Protocol):
    def put(self, key: str, body: BinaryIO, content_type: str, sha256_b64: str) -> StoredObject: ...
    def presigned_get(self, key: str, expires_s: int, filename: str) -> str: ...

class ReportGenerator(Protocol):
    report_type: str
    async def rows(self, filtros: Filtros, escopo: EscopoLeitura) -> AsyncIterator[dict]: ...
```

## Adaptador S3 (`reports/infrastructure/s3_storage.py`)
- Sessão boto3 criada com `botocore.credentials.RefreshableCredentials` alimentadas por `sts.assume_role(RoleArn, RoleSessionName=f"sgs-{user_id}", ExternalId, DurationSeconds=900)`. Em dev, se `S3_ASSUME_ROLE_ARN` estiver vazio, usa credenciais do ambiente (SeaweedFS).
- `put_object(..., ServerSideEncryption="aws:kms", SSEKMSKeyId=..., ChecksumAlgorithm="SHA256", ChecksumSHA256=...)`.
- `generate_presigned_url("get_object", Params={..., "ResponseContentDisposition": f'attachment; filename="{nome}"'}, ExpiresIn=300)`.
- `Config(signature_version="s3v4", retries={"mode": "standard"})`; `endpoint_url` configurável.
- Chamadas executadas em thread (`anyio.to_thread.run_sync`).

## Geração
- `BackgroundTasks` chama `gerar_relatorio(job_id)`; o caso de uso abre sessão própria do banco.
- Arquivo temporário (`tempfile.SpooledTemporaryFile`, 20 MB em memória) para não estourar memória; CSV via `csv.writer`, XLSX via `openpyxl` em modo `write_only`.
- Hash SHA-256 calculado durante a escrita.

## Infraestrutura na AWS (documentada, não automatizada nesta spec)
- Bucket privado com *Block Public Access*, versionamento e ciclo de vida de 90 dias em `reports/`.
- Política do bucket: `Deny` se `aws:SecureTransport = false`; `Deny` `PutObject` sem `s3:x-amz-server-side-encryption = aws:kms`.
- Papel IAM `sgs-report-writer` com `s3:PutObject`/`s3:GetObject` apenas em `arn:aws:s3:::<bucket>/reports/*` e `kms:GenerateDataKey`/`kms:Decrypt` na chave; relação de confiança exige `sts:ExternalId`.
- Exemplo das políticas em `docs/architecture/aws-iam-exemplo.md` (a criar na T7).

## Rotas
| Método e rota | Permissão | Requisitos |
|---|---|---|
| `POST /api/v1/relatorios` | `relatorio:export` | R1 |
| `GET /api/v1/relatorios` | `relatorio:export` ou `relatorio:download` | R3.5 |
| `GET /api/v1/relatorios/{id}` | idem | R3.1 |
| `GET /api/v1/relatorios/{id}/download` | `relatorio:download` | R3.2–R3.4 |

## Configuração
`S3_BUCKET`, `S3_REGION`, `S3_ENDPOINT_URL` (dev), `S3_ASSUME_ROLE_ARN`, `S3_EXTERNAL_ID`, `S3_KMS_KEY_ID`, `S3_SSE` (`aws:kms`|`AES256`), `REPORT_URL_TTL_SECONDS=300`.

## Evolução opcional
`AssumeRoleWithWebIdentity` usando um token emitido pelo Keycloak para a própria API, eliminando o segredo de longa duração do lado da API.

## Estratégia de testes
- Unidade: geradores (escopo aplicado, neutralização de fórmula, BOM, `;`).
- Integração com moto (`mock_aws`): `AssumeRole` chamado com `ExternalId` e nome de sessão; `PutObject` com SSE e checksum; URL pré-assinada com expiração de 300 s.
- Teste de configuração: em `prod`, sem `S3_ASSUME_ROLE_ARN` a API recusa iniciar.
- Integração (marcador `slow`): upload real no SeaweedFS do compose.
