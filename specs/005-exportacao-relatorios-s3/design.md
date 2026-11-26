# 005 · Exportação de relatórios para S3 · Design

- Status: **Aprovado (G2: Rafael (rafareloM), dono, em 24/11/2026)**. Registro do agente por autorização expressa dada na sessão de trabalho, com as recomendações de § Pontos para o G2 aceitas (§ Decisões do G2). Aprovação só do dono, pela exceção de `steering/sdd-workflow.md` § Exceção pontual: specs 004 e 005. **Limitação: o design não teve revisão de um segundo integrante.**
- Requisitos: requirements.md (Aprovado, G1 do Rafael em 24/11/2026)
- Decisões: ADR-0005 (exportação para S3 com STS, Aceito); ADR-0009, complemento da 011 (consultas dos relatórios em SQL explícito).
- Histórico: rascunho de 03/10/2026 (portas, adaptador S3, geração, AWS, rotas); notas de 09/11/2026 e 24/11/2026 ("Ajustes pendentes do G1"); reescrito por agente em 24/11/2026 com `/spec-design`, depois do G1. A reescrita aplica aquelas notas e cobre os critérios novos (R2.8, R2.9, R3.6, R6), a R3.2 revista e a R5, que não tinha design.

## Visão geral
1. **Pedido.** `POST /relatorios` confere a permissão de dados do tipo pedido e os filtros. Grava o pedido `pendente` com o escopo de leitura de quem pediu (`scope_snapshot`) e responde 202. A geração roda em segundo plano.
2. **Geração.** As consultas, em SQL explícito sobre as views da 011, leem só o escopo gravado. O arquivo vai para um temporário em disco, com o SHA-256 calculado durante a escrita. O hash é assinado com a chave de relatórios (R5).
3. **Envio.** Credenciais temporárias de `AssumeRole` (15 min, `ExternalId`, sessão com o id de quem pediu) e HTTPS. Criptografia no servidor e checksum SHA-256, com a resposta do armazenamento conferida (R2.8).
4. **Download.** `GET /relatorios/{id}/download` responde 200 com uma URL pré-assinada de 5 minutos no endereço público do armazenamento e o instante em que vence. Quem pediu abre a URL e o navegador baixa direto (R3.2, R3.6).
5. **Verificação.** As chaves públicas de relatórios ficam numa rota pública em JWK. Quem recebe o arquivo confere a assinatura sem a API.
6. **Laboratório.** SeaweedFS no compose com TLS e bucket criado, exposto ao navegador pelo Caddy em `s3.localhost`.

## Diagnóstico de partida (24/11/2026, `main` @ `62b373c`)
| Item | Situação |
|---|---|
| Módulo `reports` | Não existe (`steering/structure.md` o prevê) |
| `report_jobs` | Só no `docs/architecture/modelo-dados.md` § 4 |
| Permissões | `relatorio:export` e `relatorio:download` semeadas na `0003_access`, com os mesmos papéis e escopos: `GESTOR_DADOS` G, `COORD_TECNICO` A, `DIRETORIA` G, `AUDITOR` G. O comentário da semeadura deixa para esta spec o recorte "só auditoria" do `AUDITOR` |
| Dados | `vw_unit_inventory` (011) já foi escrita para "o relatório `inventario_unidades` da 005", sem dado pessoal; `vw_unit_history` traz o histórico das unidades com as colunas de escopo |
| Escopo em SQL | `src/core/escopo.py`: `parametros_de_escopo` para o fragmento fixo das consultas à mão |
| Dependências | `boto3` e `openpyxl` na `steering/tech.md`, `moto` nas ferramentas de teste; nenhum no `pyproject.toml` |
| Compose | Sem armazenamento S3; `.env.example` com `S3_ENDPOINT_URL=http://s3:8333`, que contraria a R2.7 |

## Rotas (contrato)
| Método e rota | Permissão | Entrada | Saída | Erros | Requisitos |
|---|---|---|---|---|---|
| `POST /api/v1/relatorios` | `relatorio:export`, mais a permissão de dados do tipo (§ Escopo) | `{tipo: "inventario_unidades" \| "trilha_auditoria", formato: "csv" \| "xlsx", filtros}` | 202 `{id, status: "pendente"}` | 401; 403 (sem a permissão de dados, R1.4); 422 (filtros, R1.5); 503 (exportação não configurada) | R1.1–R1.5 |
| `GET /api/v1/relatorios` | `relatorio:export` | `status` (opcional), `pagina`, `tamanho` | 200 `{itens: [Relatorio], total}`, do mais recente ao mais antigo; os do usuário, ou todos para `GESTOR_DADOS` | 401, 403, 422 | R3.5 |
| `GET /api/v1/relatorios/{id}` | `relatorio:export` | — | 200 `Relatorio`, com `integridade` se concluído | 401; 403 (nem solicitante nem escopo que cubra, R3.3); 404 | R3.1, R3.3, R5.3 |
| `GET /api/v1/relatorios/{id}/download` | `relatorio:download` | — | 200 `{url, expira_em}`, com `Cache-Control: no-store` | 401; 403 (R3.3); 404; 409 (não concluído ou vencido) | R3.2–R3.4, R3.6 |
| `GET /.well-known/relatorios-jwks.json` | pública | — | 200 `{keys: [Jwk]}`, com a chave ativa e as anteriores | — | R5.4, R5.5 |

- **`Relatorio`** = `{id, tipo, formato, filtros, status: "pendente" | "gerando" | "concluido" | "falhou", solicitado_por, criado_em, concluido_em, tamanho_bytes, vence_em, vencido, erro (genérico ou null), integridade}`.
- **`integridade`** = `{sha256 (hex), assinatura (base64url), algoritmo: "ES256", kid}`, só quando `concluido`.
- **`filtros`:**
  - `inventario_unidades`: `{distrito_id?, area_tecnica_id?, tipo_unidade_id?, status?}`; ids inexistentes dão 422.
  - `trilha_auditoria`: `{de, ate}` obrigatórios, com no máximo 366 dias (R1.5), mais `acao?` (prefixo, até 50 caracteres) e `entidade_tipo?`.
- As rotas de consulta exigem `relatorio:export`, porque `require` aceita uma permissão só e as duas permissões têm hoje a mesma matriz (D005-11).
- `/.well-known/*` já vai para a API pelo Caddy. A rota fica fora de `/api/v1`, como o JWKS da 002.

## Escopo dos relatórios (R1.3, R1.4, R3.3)
| Tipo | Permissão de dados | Escopo usado | Fonte |
|---|---|---|---|
| `inventario_unidades` | `unidade:read` | `EscopoLeitura` de `unidade:read` | `vw_unit_inventory` |
| `trilha_auditoria` | `auditoria:read` (R1.4) | `EscopoLeitura` de `auditoria:read` | Escopo global: `audit_log` sem os eventos de acesso. Escopo restrito: `vw_unit_history` no escopo |

- O `AUDITOR` não tem `unidade:read`, então só exporta a trilha. É o recorte "G (só auditoria)" da semeadura da 003, sem regra a mais.
- `scope_snapshot` guarda o `EscopoLeitura` usado (`global`, `areas`, `distritos`, `unidades`). A geração usa só ele, nunca o escopo do momento da geração.
- **Download por outra pessoa (R3.3).** Vale para o solicitante, ou para quem tem, na mesma permissão de dados, um escopo que cubra o gravado. A função pura `escopo_cobre(maior, menor)` decide:
  - global cobre tudo;
  - senão, cada conjunto (áreas, distritos, unidades) do gravado tem de estar contido no do usuário.

  A comparação é conservadora: um escopo de distrito não cobre uma lista de unidades, mesmo que elas estejam no distrito.
- **Listagem (R3.5).** O usuário vê os próprios pedidos; com o papel `GESTOR_DADOS`, vê todos, como o requisito diz.

## Modelo de dados / migrações
Migração `0005_relatorios`. A tabela fica declarada em `reports/infrastructure/tables.py`, igual à migração.

| Coluna de `report_jobs` | Tipo | Observação | Requisitos |
|---|---|---|---|
| `id` | uuid v7 | | R1.1 |
| `report_type`, `format` | texto | `CHECK` nas listas fechadas | R1.2 |
| `filters` | JSONB | já validados | R1.5 |
| `requested_by` | uuid → `users` | | R3.3, R3.5 |
| `scope_snapshot` | JSONB | escopo usado | R1.3 |
| `status` | texto | `CHECK` (`pendente`, `gerando`, `concluido`, `falhou`) | R1.1, R2.5, R2.6 |
| `storage_bucket`, `storage_key`, `storage_version_id` | texto | a versão permite remover exatamente o objeto gravado (R2.8) | R2.4, R2.8 |
| `size_bytes`, `sha256` | bigint, `CHAR(64)` | hash em hex | R2.5 |
| `signature`, `signature_alg`, `signature_kid` | texto | | R5.1, R5.3 |
| `error` | até 200 | mensagem genérica | R2.6 |
| `created_at`, `updated_at`, `started_at`, `finished_at`, `expires_at` | `timestamptz` | `expires_at = finished_at + 90 dias` (§ Configuração) | R3.2 |

- `CHECK` de coerência: `status = 'concluido'` exige `storage_key`, `sha256`, `signature`, `signature_alg` e `signature_kid` não nulos.
- Índices: `ix_report_jobs_requested_by_created_at` (`requested_by`, `created_at DESC`) e `ix_report_jobs_status_aberto` (`status`) `WHERE status IN ('pendente', 'gerando')`.
- O repositório de pedidos usa SQLAlchemy Core.
- As consultas de dados ficam em SQL escrito à mão (ADR-0009, complemento da 011), em `reports/infrastructure/sql/`, uma por arquivo e com cabeçalho de objetivo, justificativa e uso:
  - `inventario_unidades.sql`;
  - `trilha_auditoria_global.sql`;
  - `trilha_auditoria_escopo.sql`.

  O escopo entra pelo fragmento fixo de `src/core/escopo.py`.
- `docs/architecture/modelo-dados.md` § 4: acrescentar as colunas de versão e de assinatura.

## Portas e adaptadores
Domínio (`reports/domain/`), só stdlib:

```python
@dataclass(frozen=True)
class GravacaoEsperada:
    sse: Literal["aws:kms", "AES256"]
    kms_key_id: str | None          # ARN, em prod
    sha256_b64: str

@dataclass(frozen=True)
class ObjetoGravado:
    key: str
    version_id: str | None
    sse: str | None                 # ServerSideEncryption da resposta
    kms_key_id: str | None          # SSEKMSKeyId da resposta
    checksum_sha256: str | None     # ChecksumSHA256 da resposta

def conferir_gravacao(esperada: GravacaoEsperada, gravado: ObjetoGravado) -> list[str]:
    """R2.8: lista vazia se confere; senão, os campos que não conferem."""

class ArmazenamentoDeObjetos(Protocol):
    async def enviar(self, key: str, arquivo: BinaryIO, *, content_type: str, sha256_b64: str,
                     metadados: Mapping[str, str], sessao: str) -> ObjetoGravado: ...  # R2.1–R2.4, R2.7
    async def remover(self, key: str, version_id: str | None, *, sessao: str) -> None: ...  # R2.8
    async def url_de_download(self, key: str, *, nome: str, sessao: str) -> UrlAssinada: ...  # R3.2, R3.6

class GeradorDeRelatorio(Protocol):
    tipo: str
    colunas: tuple[Coluna, ...]     # nome e tipo (texto, número, data); define a neutralização
    def linhas(self, filtros: Filtros, escopo: EscopoGravado) -> AsyncIterator[Sequence[object]]: ...

class AssinadorDeRelatorio(Protocol):
    def assinar(self, sha256: bytes) -> Assinatura: ...  # kid, "ES256", valor em base64url (R5.1)
    def chaves_publicas(self) -> tuple[PublicJwk, ...]: ...  # R5.4, R5.5
```

`sessao` é o id do usuário que vai no `RoleSessionName` (`sgs-{id}`, R2.1).

### Adaptador S3 (`reports/infrastructure/s3_storage.py`)
- **Credenciais, por operação (D005-2).**
  - `sts.assume_role(RoleArn, RoleSessionName=f"sgs-{usuario_id}", ExternalId, DurationSeconds=900)` antes de cada envio, com o id de quem pediu, e antes de cada URL, com o id de quem baixa.
  - Com as credenciais devolvidas, um cliente `s3` é criado só para aquela operação. Assim a URL de 5 minutos nunca vence antes por causa das credenciais.
  - O cliente `sts` usa a identidade do ambiente de execução (papel da instância ou da tarefa, ou *web identity*), nunca chave fixa (R2.2, R2.9).
  - Em dev, sem `S3_ASSUME_ROLE_ARN`: chaves `S3_ACCESS_KEY_ID`/`S3_SECRET_ACCESS_KEY` do laboratório, que a subida recusa em `prod`.
- **Dois endereços (R3.6; D005-3).** O cliente de envio usa `S3_ENDPOINT_URL` (interno). O cliente que gera a URL usa `S3_PUBLIC_ENDPOINT_URL`: a assinatura SigV4 cobre o `host`, e a URL não pode ser reescrita depois. Em `prod` na AWS, os dois ficam vazios e valem os endereços HTTPS padrão.
- **`Config`:**
  - `signature_version="s3v4"`, `retries={"mode": "standard"}`;
  - `s3={"addressing_style": S3_ADDRESSING_STYLE}`;
  - `request_checksum_calculation="when_required"` e `response_checksum_validation="when_required"`: o checksum vai explícito, e os padrões novos do SDK (CRC32 em *trailer*) quebram armazenamentos compatíveis;
  - `verify = S3_CA_FILE` ou as CAs do sistema;
  - endereços `https://` (R2.7).
- **Envio (R2.3).** `put_object(Bucket, Key, Body, ContentType, ServerSideEncryption=S3_SSE, SSEKMSKeyId=S3_KMS_KEY_ID (só com aws:kms), ChecksumSHA256=sha256_b64, Metadata={"sgs-sha256", "sgs-kid", "sgs-assinatura"})`. Devolve `ObjetoGravado` com `VersionId`, `ServerSideEncryption`, `SSEKMSKeyId` e `ChecksumSHA256` da resposta.
- **Remoção (R2.8).** `delete_object(Bucket, Key, VersionId=...)`, para não deixar a versão ruim por trás de um *delete marker* num bucket versionado.
- **URL (R3.2, R3.6).** `generate_presigned_url("get_object", Params={Bucket, Key, ResponseContentDisposition: 'attachment; filename="sgs-{tipo}-{aaaa-mm-dd}.{formato}"', ResponseContentType}, ExpiresIn=300)`. O nome do arquivo não traz dado pessoal.
- Toda chamada do boto3 roda em `anyio.to_thread.run_sync`. Nenhuma URL, chave ou credencial vai para log.

### Assinatura (`reports/infrastructure/assinatura.py`; R5)
- **Chaves.** `REPORT_SIGNING_KEYS_FILE` (ou `REPORT_SIGNING_KEYS`), no mesmo formato e com o mesmo leitor das chaves JWT da 002: lista JSON de `{kid, pem}` EC P-256, em que a primeira assina e as demais só verificam.
- **Geração.** `uv run python -m src.tools.jwt_keys --kid rel-AAAA-MM-DD --output secrets/report-keys.json`, sem ferramenta nova.
- **Algoritmo.** ECDSA P-256 com SHA-256 sobre o hash já calculado: `sign(digest, ECDSA(Prehashed(SHA256())))`. Isso é exatamente ES256 sobre o conteúdo do arquivo. A assinatura sai em `r‖s` de 64 bytes, em base64url (RFC 7518 § 3.4), o formato que a JWK publicada descreve.
- **R5.2.** A subida recusa se algum `kid` ou chave pública de relatórios coincidir com uma das chaves JWT.
- **R5.4.** `GET /.well-known/relatorios-jwks.json` publica todas as chaves configuradas (`kty: EC`, `crv: P-256`, `alg: ES256`, `use: sig`, `kid`, `x`, `y`).
- **R5.5. Rotação:**
  - a chave nova entra no início da lista;
  - as antigas ficam no arquivo, e portanto publicadas, enquanto houver relatório assinado por elas dentro do prazo de guarda (90 dias) mais uma margem.

  O procedimento fica em `docs/operacao/verificar-relatorio.md`, junto com a verificação fora da API: um trecho em Python com `cryptography` e a JWK, e a alternativa com `openssl` (conversão de `r‖s` para DER).
- O hash é um só e aparece em três lugares: `report_jobs.sha256`, o `ChecksumSHA256` do objeto e a mensagem assinada.

## Configuração
| Variável | Exemplo (laboratório) | Regra na subida | Requisitos |
|---|---|---|---|
| `S3_BUCKET` | `sgs-relatorios` | sem ela, a exportação fica desligada (503) em dev e test; obrigatória em `prod` | R2.9 |
| `S3_REGION` | `us-east-1` | — | R2.1 |
| `S3_ENDPOINT_URL` | `https://s3:8333` | opcional; só `https://` | R2.7 |
| `S3_PUBLIC_ENDPOINT_URL` | `https://s3.localhost` | opcional (padrão: o `S3_ENDPOINT_URL`); só `https://` | R3.6, R6.2 |
| `S3_CA_FILE` | `/certs-servicos/ca.crt` | opcional; arquivo existente | R2.7, R6.1 |
| `S3_ADDRESSING_STYLE` | `path` | `virtual` (padrão) ou `path` | R6.2 |
| `S3_ASSUME_ROLE_ARN`, `S3_EXTERNAL_ID` | vazios | obrigatórios em `prod` | R2.1, R2.9 |
| `S3_KMS_KEY_ID` | vazio | obrigatório em `prod`, como ARN de chave (`arn:aws:kms:…:key/…`), para a conferência exata da R2.8 | R2.3, R2.8, R2.9 |
| `S3_SSE` | `AES256` | `aws:kms` ou `AES256`; `prod` exige `aws:kms` | R2.3, R2.9 |
| `S3_ACCESS_KEY_ID` / `S3_SECRET_ACCESS_KEY` | `sgs-lab-exemplo` / `sgs-lab-exemplo-s3` | só fora de `prod` | R2.2, R2.9 |
| `REPORT_SIGNING_KEYS_FILE` (ou `REPORT_SIGNING_KEYS`) | `/run/secrets/report-keys.json` | obrigatória com `S3_BUCKET`; em `prod`, chave de exemplo recusada; nenhuma chave igual às JWT | R5.1, R5.2 |
| `REPORT_RETENTION_DAYS` | `90` | 1 a 3650 | G1 (guarda de 90 dias) |

- **Recusas em `prod` (R2.9).** Falta de `S3_BUCKET`, `S3_ASSUME_ROLE_ARN`, `S3_EXTERNAL_ID` ou `S3_KMS_KEY_ID` em ARN; `S3_SSE` diferente de `aws:kms`; qualquer chave fixa configurada. Chave fixa é `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, ou as variáveis do SDK `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN` e `AWS_PROFILE`, que `Settings` declara só para recusar.
- A validade da URL é fixa em 300 s, no domínio, porque a R3.2 fixa o valor. O `REPORT_URL_TTL_SECONDS` do rascunho anterior sai.
- `.env.example`: o bloco S3 passa aos valores do laboratório, com `https://` (corrige a contradição com a R2.7).

## Fluxo

### Pedido (R1)
Na transação da rota:
1. Valida os filtros com Pydantic (R1.5).
2. Confere a permissão de dados: sem ela, 403 (R1.4).
3. Calcula o `EscopoLeitura`.
4. Grava o pedido `pendente` e audita `relatorio.solicitado`.
5. Responde 202 e agenda `gerar_relatorio(id)` em `BackgroundTasks` (R1.1).

### Geração e envio (R1.3, R2, R4, R5.1)
1. `UPDATE ... SET status = 'gerando', started_at = agora WHERE id = :id AND status = 'pendente'`, em transação curta. Sem linha, para.
2. Numa transação `REPEATABLE READ, READ ONLY`, as linhas saem por cursor do servidor (`stream`, lotes de 1.000), filtradas pelo `scope_snapshot` (R1.3). Cada lote é escrito em `anyio.to_thread.run_sync` (openpyxl e `csv` são bloqueantes):
   - temporário em `tempfile.SpooledTemporaryFile(max_size=20 MB)`;
   - SHA-256 atualizado a cada bloco escrito;
   - limite de 1.000.000 de linhas (o XLSX aceita 1.048.576): acima disso, falha com "Relatório grande demais; reduza o período ou os filtros".
3. Assina o hash (R5.1).
4. `enviar(...)` com a sessão do solicitante (R2.1–R2.4), na chave `reports/{aaaa}/{mm}/{tipo}/{id}.{formato}` com ano e mês do pedido em UTC (R2.4).
5. `conferir_gravacao(...)` (R2.8):
   - a SSE da resposta tem de ser a exigida e, com `aws:kms`, o `SSEKMSKeyId` igual ao ARN configurado;
   - o `ChecksumSHA256` tem de ser o enviado;
   - se algo não conferir, `remover(key, version_id)` e falha.
6. Na transação de conclusão:
   - grava `concluido` com tamanho, hash, chave, versão, assinatura e `expires_at`;
   - audita `relatorio.exportado` com `success` e, em `metadata`, tipo, formato, tamanho, hash e `kid` (R2.5).
7. **Falha** em qualquer passo (R2.6):
   - a transação aberta é desfeita;
   - outra transação grava `falhou` com mensagem genérica ("Não foi possível gerar ou enviar o relatório") e audita `relatorio.exportado` com `failure`;
   - o erro detalhado vai só para o log (sem URL, chave ou credencial).

   Nova tentativa é um pedido novo com os mesmos parâmetros, e nada a impede. O temporário é fechado sempre.
8. **Interrompido.** Na subida (lifespan), pedidos `pendente` ou `gerando` viram `falhou` com "Interrompido", como as execuções da 004. A API roda numa instância só.

### Conteúdo (R4)
- **CSV:**
  - UTF-8 com BOM, separador `;`, fim de linha `\r\n`, `csv.QUOTE_MINIMAL` (R4.1);
  - célula de texto que começa por `=`, `+`, `-`, `@`, tabulação ou `\r` ganha um `'` na frente (R4.2; OWASP, *CSV injection*);
  - colunas numéricas e de data são formatadas pelo gerador e não passam pela neutralização.
- **XLSX:**
  - `openpyxl` em `write_only`;
  - toda célula de texto é gravada como texto explícito (`data_type = "s"`), porque o openpyxl trata como fórmula qualquer texto que comece por `=` (R4.2);
  - o mesmo `'` do CSV, para o arquivo dizer o mesmo nos dois formatos.
- **Inventário.** As colunas da `vw_unit_inventory`: CNES, nome, tipo, área técnica, distrito, status, situação cadastral e as contagens. A view não tem dado pessoal (011/R4.2).
- **Trilha (R4.3):**
  - colunas: instante (fuso de Recife), ação, tipo de ator, autor (`display_name`), papéis, entidade (tipo e id), resultado e mudanças (`campo: de → para`);
  - a consulta não lê `metadata`, `ip`, `user_agent` nem `session_id`;
  - as mudanças saem como gravadas, e os valores pessoais já estão como `***` na trilha (por exemplo, o nome do gestor da unidade, `registry/domain/unidade.py`);
  - os eventos de acesso (`auth.*`, `acesso.*`, `auditoria.*`) ficam de fora, como na `vw_unit_history` (013): eles pedem `auditoria:read_acessos`.

### Download (R3.2–R3.4, R3.6)
1. Carrega o pedido; se não existe, 404.
2. Confere R3.3 (solicitante ou `escopo_cobre`); se não, 403.
3. Se não está `concluido`, ou se `expires_at` já passou, 409.
4. `url_de_download(...)` com a sessão de quem baixa.
5. Audita `relatorio.baixado`, com o `expira_em` e sem a URL (R3.4).
6. Responde 200 `{url, expira_em}` com `Cache-Control: no-store`. A URL é uma credencial de 5 minutos.

## Ambiente de demonstração (R6)
Usa o `servicos-certs` e as redes `integracoes` e `exposicao` do design da 004 (§ Ambiente). Os três nomes de certificado (`ldap`, `keycloak`, `s3`) saem de uma vez: a T8 que vier primeiro, desta spec ou da 004, cria o serviço.

| Serviço | Imagem | Redes | Papel |
|---|---|---|---|
| `s3` | `chrislusf/seaweedfs` com tag de versão fixada na T8 (nunca `latest`) | `integracoes`, `exposicao` | `weed server` com o S3 em HTTPS (certificado `s3` do `servicos-certs`), identidade do laboratório em `docker/seaweedfs/s3.json` (só `Read`, `Write`, `List` no bucket), volume `s3-data`; sem porta no host (R6.1) |
| `s3-init` | a mesma | `integracoes` | *One-shot* depois do `s3` saudável: cria o bucket `sgs-relatorios` (`weed shell`, `s3.bucket.create`), sem erro se já existir (R6.1) |
| `proxy` | `caddy:2` (existe) | + `exposicao` | Bloco novo `s3.localhost`, com `tls internal`, `reverse_proxy https://s3:8333`, CA de laboratório e `tls_server_name s3`. O `Host` original passa adiante (padrão do Caddy): a assinatura da URL foi feita com ele (R6.2) |
| `api` | (existe) | + `integracoes` | `S3_*` do laboratório; `S3_PUBLIC_ENDPOINT_URL=${SGS_PUBLIC_S3_URL:-https://s3.localhost}`; segredo `report_keys` montado como os da 002 |

- **Endereço público.** `s3.localhost` resolve para o próprio host nos navegadores. É um host, não um prefixo de caminho, porque o caminho entra na assinatura (D004-14). Com `SGS_HTTPS_PORT` diferente de 443, `SGS_PUBLIC_S3_URL` leva a porta (README).
- **Criptografia no SeaweedFS.** Conferida na primeira hora da T8 (G1). Se a resposta do `PutObject` não trouxer `ServerSideEncryption: AES256`, a T8 para e a decisão volta ao dono antes de seguir. As opções são as da pergunta de 24/11/2026: outro armazenamento compatível, ou aceitar em dev só a conferência do checksum (a R2.8 em dev ficaria sem a parte da criptografia).
- **Roteiro (R6.3).** `docs/operacao/demo-relatorios.md`:
  1. pedir o relatório pelo `/docs`;
  2. acompanhar o status;
  3. pedir o download;
  4. abrir a URL no navegador do host;
  5. conferir hash e assinatura com a JWK pública (`verificar-relatorio.md`).

  Sem tela nova (G1).
- **AWS real (G1).** Opcional, se houver conta. O documento `docs/architecture/aws-iam-exemplo.md` (T7) traz:
  - bucket privado com *Block Public Access*, versionamento e ciclo de vida de 90 dias em `reports/`;
  - política com `Deny` sem `aws:SecureTransport` e `Deny` de `PutObject` sem `aws:kms`;
  - papel `sgs-report-writer` com `s3:PutObject`, `s3:GetObject` e `s3:DeleteObjectVersion` só em `reports/*`, `kms:GenerateDataKey` e `kms:Decrypt` na chave, e confiança exigindo `sts:ExternalId`;
  - a identidade da execução com `sts:AssumeRole` só nesse papel.

## Segurança
- **Credenciais.** Sem chave fixa em `prod`, recusada na subida (R2.2, R2.9). Sessões de 15 min com `ExternalId` e o id do usuário (R2.1).
- **Transporte e repouso.** HTTPS com CA conferida em todos os enlaces (R2.7, R6.1). SSE e checksum conferidos depois do envio, não só pedidos (R2.3, R2.8).
- **Download.** URL de 5 minutos, `no-store`, nunca em log nem na auditoria; só o solicitante ou quem tem escopo que cubra (R3.2, R3.3).
- **Escopo e privacidade.** Dados só do escopo gravado no pedido (R1.3). Fórmulas neutralizadas (R4.2). Sem dado pessoal nem de acesso na trilha exportada (R4.3; LGPD em `steering/security.md`).
- **Assinatura.** Chave própria, diferente da dos tokens (R5.2), com `kid` e rotação (R5.5). Nunca primitiva criptográfica própria: `cryptography` (`steering/security.md`).
- **Auditoria** na transação do caso de uso: `relatorio.solicitado`, `relatorio.exportado` (success/failure) e `relatorio.baixado`.
- **Rotas.** Todas declaram permissão, menos a de chaves públicas (só chaves públicas, como o JWKS da 002). Há testes 401, 403 e 422.

## Decisões e alternativas
| Id | Decisão | Alternativas e por que não |
|---|---|---|
| D005-1 | Download responde 200 com `{url, expira_em}` (R3.2 revista no G1) | 307 para a URL: o token do front fica em memória e não vai num link; o `fetch` que segue o 307 exige CORS no armazenamento e traz o arquivo para a memória da página |
| D005-2 | `AssumeRole` por operação (envio e URL), com o id do usuário na sessão | `RefreshableCredentials` de longa duração (rascunho anterior): a sessão de 15 min cai dentro da janela de renovação do botocore (15 min) e seria renovada a cada chamada; e um nome de sessão fixo perderia o usuário (R2.1) |
| D005-3 | Dois clientes S3: interno para envio, público para a URL | Reescrever o host da URL: invalida a assinatura SigV4. Endereço único: a API e o navegador não alcançam o mesmo nome |
| D005-4 | Conferência da gravação por função pura do domínio, com remoção da versão gravada | Confiar no cabeçalho enviado: é o que a R2.8 veio corrigir |
| D005-5 | Em `prod`, `S3_KMS_KEY_ID` como ARN | Alias ou id: a resposta traz o ARN e a conferência exigiria uma chamada ao KMS |
| D005-6 | Assinatura ES256 (`r‖s`, base64url) sobre o SHA-256, chaves públicas em JWK numa rota pública (G1) | Certificado X.509 autoassinado: mais peças sem ganho de confiança. CMS/PKCS#7: formato pesado para o escopo. JWS com conteúdo destacado: mais um formato para quem confere |
| D005-7 | SeaweedFS (ADR-0005) atrás do Caddy em `s3.localhost`, endereçamento por caminho | MinIO e LocalStack: sem imagem gratuita utilizável (ADR-0005). Endereçamento virtual: exigiria `sgs-relatorios.s3.localhost` e certificado coringa |
| D005-8 | Consultas de dados em SQL explícito sobre as views da 011; pedidos em SQLAlchemy Core | Tudo em Core: contraria o complemento da 011 ao ADR-0009 (as consultas dos relatórios são cobradas pela disciplina) |
| D005-9 | `BackgroundTasks` com recuperação na subida | Fila com *worker*: fora do MVP (arquitetura § Worker de relatórios) |
| D005-10 | XLSX com célula de texto explícita, mais o `'` | Só o `'`: o openpyxl ainda gravaria `=...` como fórmula |
| D005-11 | Consulta e listagem exigem `relatorio:export`; download, `relatorio:download` | Uma dependência "uma ou outra": o `require` aceita uma permissão só, e as duas têm a mesma matriz; se a matriz mudar, a rota muda junto |
| D005-12 | Escopo do relatório = escopo de leitura da permissão de dados do tipo | Escopo de `relatorio:export`: ignoraria o recorte "só auditoria" do `AUDITOR` e daria dados fora do escopo de leitura (R1.3) |
| D005-13 | Validade da URL fixa em 300 s | Configurável: a R3.2 fixa 5 minutos |
| D005-14 | `request_checksum_calculation="when_required"`, com o checksum SHA-256 explícito | Padrão novo do SDK (CRC32 em *trailer*): armazenamentos compatíveis recusam |

## Riscos
| Risco | Mitigação |
|---|---|
| SeaweedFS não aplicar ou não informar a SSE `AES256` | Primeira hora da T8; se faltar, decisão do dono antes de seguir (G1). Conferido antes, na T10 (25/11/2026): aplica e informa, desde que a chave da SSE esteja configurada (abaixo) |
| Opções de TLS do S3 no `weed server` diferentes do esperado | Também na primeira hora da T8; a alternativa é o Caddy terminar o TLS interno, registrada aqui antes de seguir. Conferido na T10: HTTPS direto na porta 8333 (abaixo) |
| `moto` não devolver `ChecksumSHA256` ou `SSEKMSKeyId` no `PutObject` | Os testes da R2.8 usam evento do botocore (`after-call.s3.PutObject`) ou `Stubber`; a função de conferência é testada à parte |
| Sem conta AWS, o caminho de `prod` só é provado com `moto`, a R2.9 e o documento da T7 | Aceito no G1; tarefa opcional se houver conta |
| Exportação grande da trilha (dois anos de eventos) | Cursor do servidor, arquivo em disco e limite de linhas; o período máximo é 366 dias (R1.5) |
| URL vazada por log ou histórico | 5 minutos, `no-store`, nunca registrada; o nome do arquivo não traz dado pessoal |
| Uma instância só da API | É o desenho do projeto; mais de uma exige fila |
| Ordem com a 004 no compose (`servicos-certs`, redes) | A primeira T8 cria as peças compartilhadas com os três nomes; a outra só acrescenta o seu serviço |

### Conferência antecipada do SeaweedFS (005/T10, 25/11/2026)
Feita por agente fora do repositório, num contêiner descartável, com o `boto3` 1.43.127 do projeto e um certificado de uma CA de teste. Nenhuma decisão muda. **Resultado: a SSE `AES256` é aplicada e informada, e a frente C segue.**

- **Imagem.** `chrislusf/seaweedfs:4.53` (`weed version`: `30GB 4.53 4ab66fb76`), publicada em 08/11/2026, digest `sha256:ccad23e18639c8b98cee17e7100b95830a06077b56d8e5b006d6dcf8ec5e94a0`. É a tag que a T8 fixa.
- **Comando** (a chave da SSE vem por `--env-file`; o `s3.json` traz uma identidade de teste):

  ```bash
  docker run -d --env-file sse.env -p 127.0.0.1:18443:8333 -v <dir>:/conf:ro,Z chrislusf/seaweedfs:4.53 \
    server -dir=/data -s3 -s3.port=8333 -s3.config=/conf/s3.json \
    -s3.cert.file=/conf/certs/s3.crt -s3.key.file=/conf/certs/s3.key
  ```

- **TLS.** Com `-s3.cert.file` e `-s3.key.file`, a porta de `-s3.port` (8333) serve só HTTPS (log: `Start Seaweed S3 API Server ... at https port 8333`). HTTP nessa porta recebe 400 (`Client sent an HTTP request to an HTTPS server`). O `-s3.port.https` (porta HTTPS à parte) não foi preciso, e a T8 não precisa dele. `-s3.cacert.file` e `-s3.tlsVerifyClientCert` são de mTLS, fora do plano. O `boto3` conferiu o certificado com `verify=<ca.crt>`, e sem a CA recusou (`SSLError`). Bate com o desenho: o Caddy faz `reverse_proxy https://s3:8333` com `tls_server_name s3`, e o TLS fica no próprio SeaweedFS.
- **A SSE depende de uma chave configurada.** Sem `s3.sse.kek` ou `s3.sse.key` (`security.toml`), ou `WEED_S3_SSE_KEK` ou `WEED_S3_SSE_KEY` (ambiente), o log avisa `SSE-S3 encryption is disabled`, e o `PutObject` com `ServerSideEncryption="AES256"` recebe **500 `InternalError`** sem gravar o objeto. A falha é fechada: nada fica gravado em claro. Com `WEED_S3_SSE_KEY` (texto secreto do qual o SeaweedFS deriva a chave de 256 bits por HKDF-SHA256), a SSE funciona.
- **`PutObject`** com `ServerSideEncryption="AES256"`, `ChecksumSHA256` e `Config(signature_version="s3v4", request_checksum_calculation="when_required", response_checksum_validation="when_required", s3={"addressing_style": "path"})`: 200, com `ServerSideEncryption: AES256`, o `ChecksumSHA256` igual ao enviado e `VersionId`. Sem `SSEKMSKeyId`, como se espera em `AES256`. A `Config` com `when_required` funciona.
- **`HeadObject` e `GetObject`.** Trazem `ServerSideEncryption: AES256` e `VersionId`. O `ChecksumSHA256` só volta com `ChecksumMode="ENABLED"`. O conteúdo baixado tem o mesmo SHA-256 do enviado.
- **Checksum errado.** 400 `BadDigest`, sem gravar.
- **Sem o cabeçalho de SSE.** 200 sem `ServerSideEncryption`: o bucket não cifra por padrão. A API sempre manda o cabeçalho, e o `conferir_gravacao` pega a ausência.
- **Em disco.** Num objeto aleatório com um marcador no meio, o marcador aparece no `.dat` do volume quando o objeto vai sem SSE e não aparece quando vai com `AES256`.
- **Versionamento.** `PutBucketVersioning` com `Enabled` é aceito. `DeleteObject` com o `VersionId` responde 204 e não deixa versão nem *delete marker*: a remoção pela versão (R2.8) funciona.
- **URL pré-assinada** (SigV4, 300 s, `ResponseContentDisposition`): traz `X-Amz-Expires=300`, e o GET responde 200 com o `Content-Disposition` pedido, `x-amz-server-side-encryption: AES256` e o mesmo SHA-256.
- **Para a T8** (observações, sem mudar decisão):
  - a chave da SSE do laboratório é uma peça que § Ambiente de demonstração não lista. Sem ela, todo envio recebe 500. Como entra no compose (segredo montado ou variável) fica com os donos, junto com a T8;
  - o versionamento do bucket também tem de ser ligado no `s3-init`, além de criar o bucket. Aqui foi pelo `PutBucketVersioning`;
  - a 4.53 sobe também o Iceberg REST (8181) e o Lance (9101) em HTTP; `-s3.port.iceberg=0` e `-s3.port.lance=0` desligam os dois;
  - a telemetria vem ligada (`-master.telemetry=false` desliga);
  - o log avisa que, sem `WEED_S3_SSE_KEK_PASSPHRASE`, a KEK fica no *filer* sem cifra;
  - a identidade de teste tinha `Admin`, para criar o bucket e ligar o versionamento. A da T8 fica com `Read`, `Write` e `List`, como no design;
  - no Fedora, com SELinux, as montagens levam `:Z`.

## Estratégia de testes
Todo teste cita o critério na docstring (`"""005/R2.8"""`). Sem internet: STS e S3 por `moto` (`mock_aws`).

| Nível | Arquivo | O que prova | Requisitos |
|---|---|---|---|
| Unidade | `tests/unit/reports/test_generators.py` | BOM, `;`, `\r\n`; neutralização no CSV e no XLSX (nenhuma célula com `data_type = "f"`); números sem `'`; colunas da trilha sem dado de acesso | R1.2, R4.1–R4.3 |
| Unidade | `tests/unit/reports/test_filtros.py` | Tipos e formatos; período de até 366 dias; campos obrigatórios | R1.2, R1.5 |
| Unidade | `tests/unit/reports/test_conferencia.py` | `conferir_gravacao`: SSE ausente ou diferente, chave KMS diferente, checksum diferente | R2.8 |
| Unidade | `tests/unit/reports/test_escopo_cobre.py` | Global, subconjuntos, comparação conservadora | R3.3 |
| Unidade | `tests/unit/reports/test_assinatura.py` | Assina e confere só com a JWK publicada; conferência com `cryptography` sobre o arquivo inteiro; chave diferente da JWT; assinatura antiga confere depois da rotação | R5.1, R5.2, R5.4, R5.5 |
| Unidade | `tests/unit/core/test_config.py` | `http://` recusado; `prod` sem papel, `ExternalId` ou ARN de KMS; `S3_SSE` em `prod`; chave fixa (`S3_*` e `AWS_*`); chaves de relatório iguais às JWT; chave de exemplo | R2.2, R2.7, R2.9, R5.2 |
| Integração | `tests/integration/reports/test_report_jobs.py` | Tabela, restrições de coerência, repositório | R1.1, R2.5 |
| Integração | `tests/integration/reports/test_consultas_relatorio.py` | SQL explícito no Postgres: escopo aplicado, trilha sem eventos de acesso e com `***` | R1.3, R4.3 |
| Integração | `tests/integration/reports/test_s3_adapter.py` | `moto`: `AssumeRole` com `ExternalId`, `sgs-{id}` e 900 s; `PutObject` com SSE, checksum e chave; resposta sem SSE remove a versão; URL com o host público, `X-Amz-Expires=300` e `Content-Disposition` | R2.1, R2.3, R2.4, R2.8, R3.2, R3.6 |
| Integração | `tests/integration/reports/test_gerar_relatorio.py` | Caso de uso com armazenamento falso: concluído com hash, assinatura e `expires_at`; falha de geração ou envio com mensagem genérica e nova tentativa; conferência que falha; interrompido na subida | R2.5, R2.6, R2.8, R5.1 |
| Integração | `tests/integration/reports/test_report_routes.py` | 202; 403 da trilha sem `auditoria:read`; `AUDITOR` sem inventário; 422; status com `integridade`; download 200, 403, 404, 409; listagem própria e de `GESTOR_DADOS`; auditoria; 401 | R1.1, R1.4, R1.5, R3.1–R3.5, R5.3 |
| Integração | `tests/integration/reports/test_chaves_publicas.py` | Rota pública com a chave ativa e as anteriores, sem material privado | R5.4, R5.5 |
| Documento | `docs/architecture/aws-iam-exemplo.md` | Revisado por um integrante (T7) | R2.1, R2.3 |
| Ponta a ponta (`slow`) | `tests/e2e/test_export_s3.py` | Compose real: pedido, geração, envio ao SeaweedFS por HTTPS com SSE e checksum conferidos; download da URL pelo navegador do host (Playwright, por `s3.localhost`); hash e assinatura conferidos com a JWK pública | R2.7, R2.8, R6.1–R6.3 |

## Cobertura dos requisitos
| Requisito | Seções |
|---|---|
| R1.1 | Rotas; Fluxo § Pedido |
| R1.2 | Rotas (entrada); Modelo de dados (`CHECK`) |
| R1.3 | Escopo dos relatórios; Fluxo § Geração (2) |
| R1.4 | Escopo dos relatórios; Rotas (403) |
| R1.5 | Rotas (`filtros`); Fluxo § Pedido |
| R2.1 | Adaptador S3 (credenciais); D005-2 |
| R2.2 | Adaptador S3; Configuração (recusas em `prod`) |
| R2.3 | Adaptador S3 (envio); Configuração (`S3_SSE`, `S3_KMS_KEY_ID`) |
| R2.4 | Fluxo § Geração (4) |
| R2.5 | Fluxo § Geração (6); Modelo de dados |
| R2.6 | Fluxo § Geração (7 e 8) |
| R2.7 | Adaptador S3 (`Config`); Configuração (só `https://`); Ambiente |
| R2.8 | Portas (`conferir_gravacao`); Adaptador S3 (remoção); Fluxo § Geração (5); D005-4, D005-5 |
| R2.9 | Configuração (recusas em `prod`) |
| R3.1 | Rotas (`GET /{id}`) |
| R3.2 | Rotas; Fluxo § Download; Adaptador S3 (URL); D005-1, D005-13 |
| R3.3 | Escopo dos relatórios (`escopo_cobre`); Fluxo § Download (2) |
| R3.4 | Fluxo § Download (5) |
| R3.5 | Rotas (listagem); Escopo dos relatórios |
| R3.6 | Adaptador S3 (dois endereços); Configuração (`S3_PUBLIC_ENDPOINT_URL`); D005-3 |
| R4.1, R4.2 | Fluxo § Conteúdo; D005-10 |
| R4.3 | Fluxo § Conteúdo (trilha) |
| R5.1 | Assinatura; Fluxo § Geração (3) |
| R5.2 | Assinatura; Configuração |
| R5.3 | Rotas (`integridade`) |
| R5.4 | Rotas (`relatorios-jwks.json`); Assinatura |
| R5.5 | Assinatura (rotação) |
| R6.1 | Ambiente (`s3`, `s3-init`, `servicos-certs`) |
| R6.2 | Ambiente (bloco `s3.localhost`, endereço público) |
| R6.3 | Ambiente (roteiro); Testes ponta a ponta |

Sem cobertura: nenhum.

## Pontos para o G2
1. **Confirmações que o G1 deixou para o G2:** SeaweedFS no compose; guarda de 90 dias; assinatura ES256 com chave própria e chaves públicas em JWK (D005-6). Recomendação: confirmar as três.
2. **Consulta com `relatorio:export`** (D005-11). Recomendação: aceitar; rever se a matriz das duas permissões divergir.
3. **Ordem com a 004.** As peças compartilhadas do compose (`servicos-certs`, redes `integracoes` e `exposicao`) nascem na primeira T8. Recomendação: começar pela T8 da 005, que não depende da 003/T8, enquanto a 004 espera o porte.
4. **Criptografia no SeaweedFS:** a conferir na T8 (G1). Se faltar, a decisão volta ao dono antes de seguir.

## Decisões do G2 (Rafael, 24/11/2026)
- Confirmados: SeaweedFS no compose, guarda de 90 dias (`REPORT_RETENTION_DAYS=90`) e assinatura ES256 com chave própria e chaves públicas em JWK (D005-6, D005-7).
- A D005-11 (consulta e listagem com `relatorio:export`) fica como está escrita.
- O trabalho das specs 004 e 005 corre em três frentes simultâneas (`tasks.md`). As peças compartilhadas do compose nascem na 004/T8 (frente B), e a T8 desta spec vem no fim da frente C. Isso substitui a recomendação do ponto 3 ("começar pela T8 da 005").
- A criptografia no SeaweedFS continua sendo conferida antes de seguir (G1). Se faltar, a decisão volta ao dono.
