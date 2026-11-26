#!/bin/bash
# Laboratório na AWS (spec 005, T13): roteiro da primeira subida da instância EC2 (Ubuntu 24.04).
# O docker/aws/lab.sh subir troca os marcadores (SGS_LAB_* entre dois sublinhados) antes de enviar como
# user-data. Roda uma vez, como root, pelo cloud-init. Cada linha de progresso começa com
# "sgs-lab:" e vai para o console da instância (lab.sh estado mostra essas linhas).
#
# Nenhum segredo sai da instância: as chaves da API e as senhas do administrador e do seed são
# geradas aqui, em /opt/sgs (só root). Para ler as senhas: EC2 Instance Connect, depois
# `sudo cat /opt/sgs/credenciais-do-lab`.
set -euo pipefail

REPOSITORIO="__SGS_LAB_REPOSITORIO__"
COMMIT="__SGS_LAB_COMMIT__"
REGIAO="__SGS_LAB_REGIAO__"
BUCKET="__SGS_LAB_BUCKET__"
PAPEL_ARN="__SGS_LAB_PAPEL_ARN__"
EXTERNAL_ID="__SGS_LAB_EXTERNAL_ID__"
CHAVE_KMS_ARN="__SGS_LAB_CHAVE_KMS_ARN__"
HOST="__SGS_LAB_HOST__"

BASE=/opt/sgs
CODIGO="$BASE/sgs-api"
COMPOSE=(docker compose -f docker/compose.yml -f docker/aws/compose.aws.yml)

log() { printf 'sgs-lab: %s\n' "$*" | tee -a /dev/console; }
trap 'log "ERRO na linha $LINENO; detalhes em /var/log/cloud-init-output.log"' ERR

log "início $(date -u +%FT%TZ), commit ${COMMIT:0:12}"

# 2 GiB de swap: o t3.small tem 2 GiB de memória, e o Keycloak sozinho usa até ~700 MiB.
if ! swapon --show | grep -q /swapfile; then
	fallocate -l 2G /swapfile
	chmod 600 /swapfile
	mkswap /swapfile >/dev/null
	swapon /swapfile
	echo '/swapfile none swap sw 0 0' >>/etc/fstab
fi
log "swap ligado"

export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q ca-certificates curl git jq unzip openssl >/dev/null

# Docker Engine e Compose v2 do repositório oficial (o compose usa `subpath`, Docker 26+).
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
# shellcheck disable=SC1091 # arquivo do sistema da instância
. /etc/os-release
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
	>/etc/apt/sources.list.d/docker.list
apt-get update -q
apt-get install -y -q docker-ce docker-ce-cli containerd.io docker-compose-plugin >/dev/null
log "$(docker --version), $(docker compose version)"

# AWS CLI v2, para a sondagem feita daqui (perfil da instância, LabRole).
curl -fsSLo /tmp/awscliv2.zip https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip
unzip -q -o /tmp/awscliv2.zip -d /tmp
/tmp/aws/install --update >/dev/null
rm -rf /tmp/aws /tmp/awscliv2.zip
log "$(aws --version)"

# Código no commit fixo, sem histórico.
install -d -m 0700 "$BASE"
if [[ ! -d "$CODIGO/.git" ]]; then
	git init -q "$CODIGO"
	git -C "$CODIGO" fetch -q --depth 1 "$REPOSITORIO" "$COMMIT"
	git -C "$CODIGO" checkout -q FETCH_HEAD
fi
cd "$CODIGO"
log "código em $CODIGO ($(git rev-parse --short HEAD))"

# Sondagem decisiva da T13: aqui a LabRole assume a LabRole.
if AWS_REGION="$REGIAO" bash docker/aws/lab.sh sondar 2>&1 | sed -u 's/^/sgs-lab: sondar: /' | tee -a /dev/console; then
	log "sondagem na instância: caminho AssumeRole confirmado"
else
	log "sondagem na instância FALHOU: a exportação para o S3 não vai funcionar; ver as linhas acima"
fi

# Variáveis do compose (docker/.env, fora do Git).
umask 077
cat >docker/.env <<EOF
SGS_BORDA_SUBNET=10.231.1.0/28
SGS_BORDA_PROXY_IP=10.231.1.14
SGS_PUBLIC_URL=https://${HOST}
SGS_PUBLIC_KEYCLOAK_URL=https://keycloak.${HOST}
SGS_CORS_ORIGINS=https://${HOST}
SGS_LAB_HOST=${HOST}
SGS_LAB_REGIAO=${REGIAO}
SGS_LAB_BUCKET=${BUCKET}
SGS_LAB_PAPEL_ARN=${PAPEL_ARN}
SGS_LAB_EXTERNAL_ID=${EXTERNAL_ID}
SGS_LAB_CHAVE_KMS_ARN=${CHAVE_KMS_ARN}
EOF

# Imagem da API e, com ela, as chaves que a API monta (mesmas ferramentas do README).
"${COMPOSE[@]}" build -q api
# Nome que o Compose dá à imagem construída: <projeto>-<serviço> (projeto `sgs-api` no compose.yml).
IMAGEM=sgs-api-api
install -d -m 0700 secrets
gerar() {
	local arquivo="$1"
	shift
	[[ -s "secrets/$arquivo" ]] && return 0
	docker run --rm --user 0 -v "$CODIGO/secrets:/out" "$IMAGEM" python -m "$@" --output "/out/$arquivo" >/dev/null
	# O arquivo é montado na API, que roda sem root; a pasta continua só de root.
	chmod 0644 "secrets/$arquivo"
}
gerar jwt-keys.json src.tools.jwt_keys
gerar crypto-keys.json src.tools.crypto_keys
gerar report-keys.json src.tools.jwt_keys --kid "rel-lab-$(date +%F)"
log "chaves geradas em $CODIGO/secrets"

"${COMPOSE[@]}" up -d --build --wait --wait-timeout 900
log "compose no ar"

# Administrador e dados de demonstração, com senhas só desta instância.
CREDENCIAIS="$BASE/credenciais-do-lab"
if [[ ! -s "$CREDENCIAIS" ]]; then
	senha_seed="$(openssl rand -base64 18)"
	senha_admin="$(openssl rand -base64 18)"
	# As senhas entram pela entrada padrão, nunca na linha de comando (visível no `ps`).
	# shellcheck disable=SC2016 # o $(cat) roda dentro do contêiner
	printf '%s' "$senha_seed" | "${COMPOSE[@]}" exec -T api \
		sh -c 'SGS_SEED_SENHA="$(cat)" exec sgs-admin seed demo' >/dev/null
	# shellcheck disable=SC2016
	printf '%s' "$senha_admin" | "${COMPOSE[@]}" exec -T api \
		sh -c 'SGS_SENHA_INICIAL="$(cat)" exec sgs-admin create-user --username admin --nome "Administrador do laboratório"' >/dev/null
	printf 'admin: %s\nusuários do seed: %s\n' "$senha_admin" "$senha_seed" >"$CREDENCIAIS"
	chmod 0600 "$CREDENCIAIS"
	unset senha_seed senha_admin
fi
log "administrador e seed prontos (senhas em $CREDENCIAIS)"
log "pronto: https://${HOST}/ e https://keycloak.${HOST}/"
