#!/bin/sh
# TLS entre a API e o PostgreSQL (spec 011, R10.3 a R10.5). Roda no serviço one-shot `db-certs`
# do compose, antes do banco, com o volume `db-certs` montado em /certs.
#
# Se faltar algum arquivo, gera uma CA de desenvolvimento e um certificado do servidor com SAN
# `db` (o nome que a API confere em verify-full). A chave da CA fica só no diretório temporário
# deste container e some no fim: ninguém mais assina com ela. Nada disso vai para o Git.
#
# Layout do volume (cada serviço monta só a sua parte, por subpath):
#   ca/ca.crt            certificado da CA, montado na API          (root, 0644)
#   server/server.crt    certificado do servidor, montado no banco  (root, 0644)
#   server/server.key    chave do servidor, montada no banco        (uid 999 = postgres, 0600)
# Para gerar de novo, apague o volume (`docker compose -f docker/compose.yml down -v`).
set -eu

destino=/certs
if [ -s "$destino/ca/ca.crt" ] && [ -s "$destino/server/server.crt" ] \
    && [ -s "$destino/server/server.key" ]; then
    echo "db-certs: certificados já existem; nada a fazer"
    exit 0
fi

apk add --no-cache --quiet openssl

umask 077
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

cat > "$tmp/ca.cnf" <<'EOF'
[req]
prompt = no
distinguished_name = dn
x509_extensions = ext
[dn]
CN = sgs-api CA de desenvolvimento (banco)
[ext]
basicConstraints = critical, CA:TRUE, pathlen:0
keyUsage = critical, keyCertSign, cRLSign
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid:always
EOF

cat > "$tmp/server.ext" <<'EOF'
basicConstraints = critical, CA:FALSE
keyUsage = critical, digitalSignature
extendedKeyUsage = serverAuth
subjectAltName = DNS:db
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid, issuer
EOF

openssl req -x509 -new -config "$tmp/ca.cnf" -days 3650 -noenc \
    -newkey ec -pkeyopt ec_paramgen_curve:P-256 -keyout "$tmp/ca.key" -out "$tmp/ca.crt"
openssl req -new -subj "/CN=db" -noenc \
    -newkey ec -pkeyopt ec_paramgen_curve:P-256 -keyout "$tmp/server.key" -out "$tmp/server.csr"
openssl x509 -req -in "$tmp/server.csr" -CA "$tmp/ca.crt" -CAkey "$tmp/ca.key" \
    -set_serial "0x$(openssl rand -hex 16)" -days 825 -extfile "$tmp/server.ext" \
    -out "$tmp/server.crt"
# Mesma exigência do Python 3.13 em verify-full (VERIFY_X509_STRICT).
openssl verify -x509_strict -CAfile "$tmp/ca.crt" "$tmp/server.crt" > /dev/null

install -d -m 0755 -o 0 -g 0 "$destino/ca" "$destino/server"
install -m 0600 -o 999 -g 999 "$tmp/server.key" "$destino/server/server.key"
install -m 0644 -o 0 -g 0 "$tmp/server.crt" "$destino/server/server.crt"
install -m 0644 -o 0 -g 0 "$tmp/ca.crt" "$destino/ca/ca.crt"
echo "db-certs: CA de desenvolvimento e certificado do servidor (SAN db) gerados"
