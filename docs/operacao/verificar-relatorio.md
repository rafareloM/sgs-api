# Verificar a assinatura de um relatório exportado

Procedimento da spec 005 (R5.1 a R5.5; design § Assinatura, D005-6). Serve a quem recebe um relatório exportado e quer confirmar que ele saiu da plataforma sem alteração, e a quem opera as chaves.

- **Estado em 25/11/2026:** a chave de assinatura e a rota de chaves públicas estão prontas (005/T9). Ainda faltam a assinatura na geração (T5), a consulta com `integridade` (T6) e o segredo no compose (T8).

## O que é assinado
- **Mensagem:** o SHA-256 do arquivo, sobre os bytes exatos que foram baixados. Assinar esse hash com `ECDSA(Prehashed(SHA256()))` dá o mesmo resultado que ES256 sobre o arquivo inteiro. Por isso a conferência lê o arquivo, não o hash.
- **Algoritmo:** ES256, isto é, ECDSA P-256 com SHA-256.
- **Formato da assinatura:** `r‖s` (64 bytes) em base64url sem `=` (RFC 7518 § 3.4). Não é DER: o `openssl` precisa da conversão abaixo.
- **`kid`:** diz qual chave assinou.
- **Onde estão os dados do relatório:**
  - `integridade`, na consulta `GET /api/v1/relatorios/{id}` (R5.3): `{"sha256": "<hex>", "assinatura": "<base64url>", "algoritmo": "ES256", "kid": "rel-2026-11"}`;
  - os mesmos valores nos metadados do objeto no bucket: `sgs-sha256`, `sgs-assinatura` e `sgs-kid`.
- **Chaves públicas:** `GET /.well-known/relatorios-jwks.json`. A rota é pública e devolve JWK (`kty` `EC`, `crv` `P-256`, `alg` `ES256`, `use` `sig`, `kid`, `x`, `y`), com a chave ativa e as anteriores (R5.4, R5.5).
- **Chaves próprias:** as chaves dos relatórios não são as dos access tokens (`/.well-known/jwks.json`, spec 002). A API recusa iniciar se um `kid` ou uma chave coincidir com uma das chaves JWT (R5.2).

## Conferir fora da API
São três arquivos na mesma pasta:
- `relatorio.csv` (ou `.xlsx`): o arquivo recebido;
- `integridade.json`: o objeto `integridade` da consulta do relatório;
- `jwks.json`: as chaves públicas.

Para obter as chaves:

```bash
curl -s https://<endereço da plataforma>/.well-known/relatorios-jwks.json > jwks.json
```

**Confiança.** A chave pública só vale o que vale o canal por onde ela veio. Baixe-a por HTTPS com o certificado conferido (sem `-k`; no laboratório, `--cacert secrets/caddy-root.crt`, ver README), ou use uma cópia do JWKS obtida desse jeito antes. Não há certificado X.509 da chave (D005-6).

### Em Python (`cryptography`)
Salve como `verificar_relatorio.py` e rode `python verificar_relatorio.py relatorio.csv integridade.json jwks.json`. Ele precisa só do pacote `cryptography`.

```python
"""Confere um relatório do SGS: python verificar_relatorio.py relatorio.csv integridade.json jwks.json"""

import base64
import hashlib
import json
import sys
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature


def base64url(texto: str) -> bytes:
    return base64.urlsafe_b64decode(texto + "=" * (-len(texto) % 4))


arquivo, integridade, jwks = (Path(p) for p in sys.argv[1:4])
conteudo = arquivo.read_bytes()
dados = json.loads(integridade.read_text(encoding="utf-8"))
chaves = {chave["kid"]: chave for chave in json.loads(jwks.read_text(encoding="utf-8"))["keys"]}

if dados["algoritmo"] != "ES256":
    sys.exit(f"algoritmo inesperado: {dados['algoritmo']}")
if hashlib.sha256(conteudo).hexdigest() != dados["sha256"]:
    sys.exit("o SHA-256 do arquivo não é o do relatório: o arquivo foi alterado ou é outro")
if dados["kid"] not in chaves:
    sys.exit(f"a chave {dados['kid']} não está no JWKS")

jwk = chaves[dados["kid"]]
x = int.from_bytes(base64url(jwk["x"]), "big")
y = int.from_bytes(base64url(jwk["y"]), "big")
publica = ec.EllipticCurvePublicNumbers(x, y, ec.SECP256R1()).public_key()
r_s = base64url(dados["assinatura"])
der = encode_dss_signature(int.from_bytes(r_s[:32], "big"), int.from_bytes(r_s[32:], "big"))
try:
    publica.verify(der, conteudo, ec.ECDSA(hashes.SHA256()))
except InvalidSignature:
    sys.exit("assinatura inválida")
print(f"assinatura válida (kid {dados['kid']})")
```

Sai com 0 e `assinatura válida (kid …)`. Se o hash, a chave ou a assinatura não conferirem, sai com 1 e diz o motivo.

### Com `openssl`, sem Python
Precisa do OpenSSL 3, do `jq` e dos utilitários do coreutils. Rode em `bash`, na pasta dos três arquivos.

```bash
b64url_hex() {  # base64url sem "=" → hexadecimal
  local s=$1
  while [ $(( ${#s} % 4 )) -ne 0 ]; do s="$s="; done
  printf '%s' "$s" | tr '_-' '/+' | openssl base64 -d -A | od -An -v -tx1 | tr -d ' \n'
}

# 1. O hash do arquivo tem de ser o de integridade.json.
sha256sum relatorio.csv
jq -r .sha256 integridade.json

# 2. A chave do kid que assinou, de JWK para PEM.
KID=$(jq -r .kid integridade.json)
X=$(jq -r --arg kid "$KID" '.keys[] | select(.kid == $kid) | .x' jwks.json)
Y=$(jq -r --arg kid "$KID" '.keys[] | select(.kid == $kid) | .y' jwks.json)
cat > chave.cnf <<EOF
asn1=SEQUENCE:spki
[spki]
algoritmo=SEQUENCE:algoritmo
chave=FORMAT:HEX,BITSTRING:04$(b64url_hex "$X")$(b64url_hex "$Y")
[algoritmo]
tipo=OID:id-ecPublicKey
curva=OID:prime256v1
EOF
openssl asn1parse -genconf chave.cnf -noout -out chave.der
openssl pkey -pubin -inform DER -in chave.der -out chave.pem

# 3. A assinatura, de r‖s para DER.
R_S=$(b64url_hex "$(jq -r .assinatura integridade.json)")
cat > assinatura.cnf <<EOF
asn1=SEQUENCE:assinatura
[assinatura]
r=INTEGER:0x${R_S:0:64}
s=INTEGER:0x${R_S:64:64}
EOF
openssl asn1parse -genconf assinatura.cnf -noout -out assinatura.der

# 4. A conferência, sobre o arquivo inteiro.
openssl dgst -sha256 -verify chave.pem -signature assinatura.der relatorio.csv
```

Com o arquivo íntegro, sai `Verified OK`. Com o arquivo alterado, sai `Verification failure`, com código 1. Os dois procedimentos foram conferidos em 25/11/2026 com OpenSSL 3.5, em 24 assinaturas geradas pelo adaptador da API, inclusive com `r` e `s` de bit alto.

## Gerar a chave
```bash
mkdir -p secrets
uv run python -m src.tools.jwt_keys --kid rel-$(date +%F) --output secrets/report-keys.json
```

- **Só na primeira vez.** O comando sobrescreve o arquivo e apaga as chaves anteriores, que ainda conferem os relatórios assinados antes (R5.5). Com o arquivo já criado, siga a [rotação](#rotação-r55).
- **Formato.** É o mesmo das chaves JWT, sem ferramenta nova: lista JSON de `{kid, pem}` EC P-256, em que a primeira chave assina e todas são publicadas.
- **Chave própria.** A chave e o `kid` têm de ser outros. O prefixo `rel-` evita o `kid` de data que as chaves JWT usam por padrão, e a API recusa iniciar se houver coincidência (R5.2).
- **Leitura.** A API lê `REPORT_SIGNING_KEYS_FILE` (caminho do arquivo montado) ou `REPORT_SIGNING_KEYS` (o JSON), só uma das duas.
- **Em `prod`:** `kid` com `troque`, `exemplo`, `example`, `changeme` ou `change-me` é recusado.
- **Sem chave:** nada é assinado e a rota publica `{"keys": []}`.
- **Segredo.** O arquivo é segredo: fica em `secrets/`, fora do Git, e nunca vai para log.

## Rotação (R5.5)
1. Gere a chave nova num arquivo à parte, em `secrets/`, fora do Git (ele também tem chave privada):

   ```bash
   uv run python -m src.tools.jwt_keys --kid rel-$(date +%F) --output secrets/report-keys.nova.json
   ```

2. Ponha a chave nova no início da lista e mantenha as antigas. Cada comando só roda se o anterior deu certo: se o `jq` falhar, o arquivo de chaves fica como estava.

   ```bash
   jq -s '.[0] + .[1]' secrets/report-keys.nova.json secrets/report-keys.json > secrets/report-keys.junta.json &&
     mv secrets/report-keys.junta.json secrets/report-keys.json &&
     rm secrets/report-keys.nova.json
   ```

3. Reinicie a API. Os relatórios novos saem com o `kid` novo. Os antigos continuam conferíveis, porque as chaves antigas seguem publicadas.
4. Retire uma chave antiga só quando nenhum relatório assinado por ela estiver mais no bucket: o prazo de guarda (`REPORT_RETENTION_DAYS`, 90 dias) contado a partir da rotação, mais uma margem.
5. Não reaproveite um `kid`.

**Chave privada vazada.** Quem tem o arquivo assina em nome da plataforma. Tire a chave da lista na hora e reinicie a API. As assinaturas feitas com ela deixam de conferir pela rota; gere de novo os relatórios que ainda forem necessários.
