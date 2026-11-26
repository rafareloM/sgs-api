# Demonstração da exportação de relatórios

Roteiro da spec 005 (R6.3; design § Ambiente de demonstração). Mostra, no ambiente local, o pedido de um relatório, a geração em segundo plano, o envio ao S3 local (SeaweedFS) por HTTPS com criptografia e checksum conferidos, o download pelo navegador e a conferência do hash e da assinatura com a chave pública. Leva uns 10 minutos. Sem tela nova (G1): tudo pela API.

- **Teste que automatiza o roteiro:** `uv run pytest tests/e2e/test_export_s3.py -m slow`.
- **Senhas:** as do laboratório (`sgs-lab-exemplo*`) são fixas, versionadas e só locais; a API as recusa em `prod` (R2.9). A senha do usuário que pede o relatório é sua: digite-a quando o comando pedir e não a grave em arquivo.

## 0. Preparar
1. Gere, uma vez, os segredos do compose (README § Subir o ambiente), inclusive os dois desta spec: a chave de assinatura dos relatórios e a chave da SSE do S3 local. O `s3_sse_key` não sobrescreve um arquivo que já existe: uma chave nova deixaria ilegível o que o SeaweedFS já cifrou.

   ```bash
   uv run python -m src.tools.jwt_keys --kid rel-$(date +%F) --output secrets/report-keys.json
   uv run python -m src.tools.s3_sse_key --output secrets/s3-security.toml
   ```

2. Suba o ambiente. O `s3-init` cria o bucket `sgs-relatorios` e liga o versionamento, sem erro se já existirem:

   ```bash
   docker compose -f docker/compose.yml up -d --build --wait
   docker compose -f docker/compose.yml ps -a s3-init    # Exited (0)
   ```

3. Crie um gestor de dados local, que pode exportar os dois tipos de relatório:

   ```bash
   read -rsp 'Senha do gestor: ' SGS_SENHA_INICIAL; echo
   docker compose -f docker/compose.yml exec -e SGS_SENHA_INICIAL="$SGS_SENHA_INICIAL" api \
     sgs-admin create-user --username gestor --nome "Gestor de dados" --papel GESTOR_DADOS
   ```

4. Prepare o terminal e entre. O `curl -k` aceita o certificado `tls internal` do Caddy; use isso só no laboratório. No primeiro acesso, o 2FA é cadastrado aqui, e `totp` gera o código a partir da URI:

   ```bash
   API=https://localhost/api/v1   # com SGS_HTTPS_PORT, use a porta de SGS_PUBLIC_URL
   json() { curl -sk -H 'Content-Type: application/json' "$@"; }
   totp() { uv run python -c 'import sys, urllib.parse as u, pyotp
   q = u.parse_qs(u.urlsplit(sys.argv[1]).query)
   print(pyotp.TOTP(q["secret"][0]).now())' "$1"; }

   read -rsp 'Senha do gestor: ' SENHA; echo
   MFA=$(jq -n --arg p "$SENHA" '{username: "gestor", password: $p}' | json "$API/auth/login" -d @- | jq -r .mfa_token)
   unset SENHA
   URI=$(json "$API/auth/mfa/enroll" -d "{\"mfa_token\": \"$MFA\"}" | jq -r .otpauth_uri)
   TOKEN=$(json "$API/auth/mfa/confirm" -d "{\"mfa_token\": \"$MFA\", \"code\": \"$(totp "$URI")\"}" | jq -r .access_token)
   AUT="Authorization: Bearer $TOKEN"
   ```

## 1. Pedir o relatório (R1.1 a R1.5)
```bash
ID=$(json "$API/relatorios" -H "$AUT" -d '{"tipo": "inventario_unidades", "formato": "xlsx"}' | jq -r .id)
echo "$ID"
```

- **Esperado:** 202 com `status: "pendente"`. O pedido grava o escopo de leitura de quem pediu, e a geração usa só ele (R1.3).
- **Trilha:** `{"tipo": "trilha_auditoria", "formato": "csv", "filtros": {"de": "2026-11-01T00:00:00-03:00", "ate": "2026-12-01T00:00:00-03:00"}}`. Período maior que 366 dias dá 422 (R1.5); quem não tem `auditoria:read` recebe 403 (R1.4).
- **Sem S3:** sem `S3_BUCKET` (ou sem a chave de assinatura), o pedido responde 503.

## 2. Acompanhar o status (R3.1, R5.3)
```bash
json "$API/relatorios/$ID" -H "$AUT" | jq '{status, tamanho_bytes, vence_em, erro, integridade}'
```

- **Esperado:** `status: "concluido"` em poucos segundos, com `integridade` (`sha256`, `assinatura`, `algoritmo: "ES256"`, `kid`).
- `concluido` quer dizer que o SeaweedFS **informou** a criptografia `AES256` e o mesmo checksum SHA-256 que a API mandou (R2.8). Se não informasse, a API removeria a versão gravada e o pedido ficaria `falhou`, com a mensagem genérica.
- A listagem fica em `GET $API/relatorios` (os seus; todos, para o `GESTOR_DADOS`, R3.5).

## 3. Pedir o download (R3.2, R3.4, R3.6)
```bash
json "$API/relatorios/$ID/download" -H "$AUT" -D - | grep -i cache-control   # no-store
URL=$(json "$API/relatorios/$ID/download" -H "$AUT" | jq -r .url)
```

- **Esperado:** 200 com `{url, expira_em}`, `Cache-Control: no-store`. A URL vale 5 minutos (`X-Amz-Expires=300`), aponta para `https://s3.localhost` e é uma credencial: não a cole em chat nem em ticket. A auditoria grava `relatorio.baixado` com o vencimento, sem a URL.

## 4. Abrir a URL no navegador do host (R6.2)
Cole `$URL` no navegador (`echo "$URL"`). Os navegadores levam `*.localhost` à própria máquina, e o Caddy repassa ao SeaweedFS com o mesmo `Host` que a assinatura cobre. O arquivo vem como anexo, `sgs-inventario_unidades-AAAA-MM-DD.xlsx`.

- O navegador avisa do certificado `tls internal` do Caddy na primeira vez (README § Subir o ambiente, para confiar na CA).
- No `curl`, sem navegador: `curl -k --resolve s3.localhost:443:127.0.0.1 -o relatorio.xlsx "$URL"`.
- Depois de 5 minutos, a mesma URL deixa de valer: peça outra no passo 3.

## 5. Conferir hash e assinatura com a JWK pública (R5.1, R5.4)
Siga [verificar-relatorio.md](verificar-relatorio.md): o hash do arquivo baixado tem de ser o `integridade.sha256`, e a assinatura confere com a chave do `kid` publicada em `/.well-known/relatorios-jwks.json`, sem a API.

```bash
sha256sum sgs-inventario_unidades-*.xlsx
json "$API/relatorios/$ID" -H "$AUT" | jq -r .integridade.sha256
```

## O que fica de fora do laboratório
- A conta AWS real (papel, `ExternalId`, KMS) está em [aws-iam-exemplo.md](../architecture/aws-iam-exemplo.md) (005/T7). Em `prod`, a API recusa as chaves fixas deste laboratório e exige `aws:kms` (R2.9).
- O SeaweedFS guarda a chave de cifra de chaves no próprio *filer*, sem cifra (`WEED_S3_SSE_KEK_PASSPHRASE` vazio; log `the KEK will be stored on the filer in plaintext`). Aceitável para dados de demonstração; não é o modelo de produção.
