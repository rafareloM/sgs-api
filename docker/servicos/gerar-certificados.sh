#!/bin/sh
# TLS dos serviços de laboratório (spec 004, design § Certificados; compartilhado com a 005). Roda
# no serviço one-shot `servicos-certs` do compose, com o volume `servicos-certs` em /certs. É
# separado do `db-certs` (D004-8): a chave de cada CA some, então um volume não ganha nomes novos.
#
# Se faltar algum arquivo, gera uma CA de laboratório e um certificado de servidor para cada
# serviço, com SAN igual ao nome do serviço na rede (o alias `ldap-nome-errado` fica de fora de
# propósito, para o teste da 004/R1.13). A chave da CA fica só no diretório temporário deste
# contêiner e some no fim. Nada disso vai para o Git.
#
# Layout do volume (cada serviço monta só a sua parte, por subpath):
#   ca/ca.crt                      CA, montada na API e no proxy        (root, 0644)
#   <serviço>/server.crt           certificado do servidor              (root, 0644)
#   <serviço>/server.key           chave, com o uid do usuário do contêiner do serviço (0600):
#                                  ldap 389 (fixado no docker/ldap/Dockerfile), keycloak 1000
#                                  (usuário da imagem), s3 1000 (o entrypoint do SeaweedFS troca
#                                  para o usuário `seaweed`, uid 1000, com su-exec; com a chave
#                                  de root, o TLS do S3 trava sem erro no log, 005/T8)
# Para gerar de novo, apague o volume (`docker compose -f docker/compose.yml down -v`).
set -eu

destino=/certs
servicos="ldap:389 keycloak:1000 s3:1000"

faltando=0
[ -s "$destino/ca/ca.crt" ] || faltando=1
for item in $servicos; do
    nome=${item%%:*}
    [ -s "$destino/$nome/server.crt" ] && [ -s "$destino/$nome/server.key" ] || faltando=1
done
if [ "$faltando" -eq 0 ]; then
    # Volumes de antes da 005/T8 têm a chave do s3 com o uid 0: o dono é acertado a cada subida.
    for item in $servicos; do
        nome=${item%%:*}
        uid=${item##*:}
        chown "$uid:$uid" "$destino/$nome/server.key"
    done
    echo "servicos-certs: certificados já existem; nada a fazer"
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
CN = sgs-api CA de laboratório (serviços)
[ext]
basicConstraints = critical, CA:TRUE, pathlen:0
keyUsage = critical, keyCertSign, cRLSign
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid:always
EOF

openssl req -x509 -new -config "$tmp/ca.cnf" -days 3650 -noenc \
    -newkey ec -pkeyopt ec_paramgen_curve:P-256 -keyout "$tmp/ca.key" -out "$tmp/ca.crt"

install -d -m 0755 -o 0 -g 0 "$destino/ca"
for item in $servicos; do
    nome=${item%%:*}
    uid=${item##*:}
    cat > "$tmp/$nome.ext" <<EOF
basicConstraints = critical, CA:FALSE
keyUsage = critical, digitalSignature
extendedKeyUsage = serverAuth
subjectAltName = DNS:$nome
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid, issuer
EOF
    openssl req -new -subj "/CN=$nome" -noenc \
        -newkey ec -pkeyopt ec_paramgen_curve:P-256 -keyout "$tmp/$nome.key" -out "$tmp/$nome.csr"
    openssl x509 -req -in "$tmp/$nome.csr" -CA "$tmp/ca.crt" -CAkey "$tmp/ca.key" \
        -set_serial "0x$(openssl rand -hex 16)" -days 825 -extfile "$tmp/$nome.ext" \
        -out "$tmp/$nome.crt"
    # Mesma exigência do Python 3.13 (VERIFY_X509_STRICT), que a API usa para falar com eles.
    openssl verify -x509_strict -CAfile "$tmp/ca.crt" "$tmp/$nome.crt" > /dev/null

    install -d -m 0755 -o 0 -g 0 "$destino/$nome"
    install -m 0600 -o "$uid" -g "$uid" "$tmp/$nome.key" "$destino/$nome/server.key"
    install -m 0644 -o 0 -g 0 "$tmp/$nome.crt" "$destino/$nome/server.crt"
done
install -m 0644 -o 0 -g 0 "$tmp/ca.crt" "$destino/ca/ca.crt"
echo "servicos-certs: CA de laboratório e certificados de ldap, keycloak e s3 gerados"
