#!/usr/bin/env bash
# Laboratório das specs 004 e 005 numa conta AWS Academy Learner Lab (spec 005, T13).
#
# Credenciais: só pela cadeia padrão do AWS CLI (~/.aws/credentials, variáveis AWS_* ou o perfil
# da instância). Nunca por argumento, nunca no repositório. A saída não mostra segredo nem id da
# conta: números de 12 dígitos saem como <ID_DA_CONTA>, e o nome da sessão (que no Learner Lab
# traz o e-mail de quem roda) sai como <SESSAO>.
#
# Cada recurso leva a etiqueta Projeto=sgs-lab e é achado por ela. Guia: docs/operacao/laboratorio-aws.md.
#
# Variáveis opcionais:
#   SGS_LAB_IPS         CIDRs que podem abrir a 443, separados por vírgula (padrão: o seu IP/32)
#   SGS_LAB_COMMIT      commit que a instância clona (padrão: HEAD; precisa estar no GitHub)
#   SGS_LAB_TIPO        tipo da instância (padrão: t3.small)
#   SGS_LAB_REPOSITORIO repositório que a instância clona
set -Eeuo pipefail
shopt -s inherit_errexit

REGIAO="${AWS_REGION:-${AWS_DEFAULT_REGION:-us-east-1}}"
ETIQUETA_CHAVE="Projeto"
ETIQUETA_VALOR="sgs-lab"
FILTRO_ETIQUETA="Name=tag:${ETIQUETA_CHAVE},Values=${ETIQUETA_VALOR}"
PAPEL_DO_LAB="LabRole"
PERFIL_DA_INSTANCIA="LabInstanceProfile"
EXTERNAL_ID_SONDAGEM="sgs-lab-sondagem"
NOME_DO_GRUPO="sgs-lab"
PREFIXO_DO_BUCKET="sgs-lab-relatorios-"
RETENCAO_DIAS=90
TIPO="${SGS_LAB_TIPO:-t3.small}"
DISCO_GIB=20
REPOSITORIO="${SGS_LAB_REPOSITORIO:-https://github.com/rafareloM/sgs-api.git}"
PARAMETRO_AMI="/aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id"
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

uso() {
	cat >&2 <<-'FIM'
		uso: docker/aws/lab.sh <subcomando>
		  sondar               confere AssumeRole na LabRole e PutObject com aws:kms (bucket temporário)
		  subir                cria grupo de segurança, IP elástico, bucket e a instância
		  estado               mostra instância, endereços, lista da 443, bucket e o progresso da subida
		  liberar-ip           troca a lista de IPs da 443 (SGS_LAB_IPS ou o seu IP)
		  parar | ligar        para ou liga a instância (o IP elástico fica)
		  destruir --confirmo  apaga a instância, o IP, o bucket (com todas as versões) e o grupo
	FIM
}

ok() { printf 'OK     %s\n' "$*"; }
falha() { printf 'FALHA  %s\n' "$*"; }
nota() { printf '       %s\n' "$*"; }

# Só no processo principal: um erro dentro de $(...) não repete a mensagem.
trap '[[ $BASHPID == "$$" ]] && falha "interrompido na linha $LINENO; o que já foi criado fica (veja: lab.sh estado)"' ERR

# Tira o id da conta (12 dígitos) de qualquer texto que vá para a tela.
mascarar() { sed -E 's/(^|[^0-9])[0-9]{12}([^0-9]|$)/\1<ID_DA_CONTA>\2/g'; }

# ARN de quem roda, sem o id da conta e sem o nome da sessão (no Learner Lab ele traz o e-mail).
mascarar_arn() { sed -E 's#(:assumed-role/[^/]+)/.*#\1/<SESSAO>#' | mascarar; }

# Primeira linha útil de um erro, sem o id da conta nem nome de sessão.
resumo_do_erro() { grep -m1 -E '[^[:space:]]' "$1" | sed -E 's#(:assumed-role/[^/ ]+)/[^ ]*#\1/<SESSAO>#g' | mascarar; }

# AWS CLI na região do laboratório. Um erro sai numa linha só, já mascarada, no stderr.
aws_() {
	local erro saida rc=0
	erro="$(mktemp)"
	saida="$(aws --region "$REGIAO" --output json "$@" 2>"$erro")" || rc=$?
	if ((rc != 0)); then
		printf 'aws %s %s: %s\n' "$1" "$2" "$(resumo_do_erro "$erro")" >&2
		rm -f "$erro"
		return "$rc"
	fi
	rm -f "$erro"
	[[ -z "$saida" ]] || printf '%s\n' "$saida"
}

precisa() {
	local programa
	for programa in "$@"; do
		command -v "$programa" >/dev/null || {
			falha "falta o programa '$programa' no PATH"
			exit 1
		}
	done
}

sha256_base64() {
	python3 -I -c 'import base64, hashlib, sys; print(base64.b64encode(hashlib.sha256(open(sys.argv[1], "rb").read()).digest()).decode())' "$1"
}

aleatorio_hex() { od -An -N6 -tx1 /dev/urandom | tr -d ' \n'; }

# --- sondar ---------------------------------------------------------------------------------------

sondar() {
	precisa aws jq python3 od
	local temp erro identidade conta quem papel
	temp="$(mktemp -d)"
	erro="$temp/erro"
	BUCKET_SONDAGEM=""
	# shellcheck disable=SC2064 # o caminho da pasta é fixado agora, de propósito
	trap "limpar_sondagem; rm -rf '$temp'" EXIT

	if ! identidade="$(aws_ sts get-caller-identity 2>"$erro")"; then
		falha "sem credenciais válidas na cadeia padrão do AWS CLI: $(resumo_do_erro "$erro")"
		nota "Copie o bloco de 'AWS Details' do Learner Lab para ~/.aws/credentials (o lab dura ~4 h)."
		return 1
	fi
	conta="$(jq -r .Account <<<"$identidade")"
	quem="$(jq -r .Arn <<<"$identidade")"
	papel="arn:aws:iam::${conta}:role/${PAPEL_DO_LAB}"
	ok "identidade: $(mascarar_arn <<<"$quem") (região $REGIAO)"
	if [[ "$quem" != *":assumed-role/${PAPEL_DO_LAB}/"* ]]; then
		nota "Daqui o AssumeRole testa '$(cut -d/ -f2 <<<"$quem") -> ${PAPEL_DO_LAB}'. Quem decide é"
		nota "a sondagem na instância, onde a ${PAPEL_DO_LAB} assume a ${PAPEL_DO_LAB}."
	fi

	local falhas=0 assumiu=0 credenciais=""
	if credenciais="$(aws_ sts assume-role --role-arn "$papel" \
		--role-session-name sgs-sondagem --external-id "$EXTERNAL_ID_SONDAGEM" \
		--duration-seconds 900 2>"$erro")"; then
		assumiu=1
		ok "sts:AssumeRole em ${PAPEL_DO_LAB}, com ExternalId, 900 s"
	else
		falhas=$((falhas + 1))
		falha "sts:AssumeRole em ${PAPEL_DO_LAB}: $(resumo_do_erro "$erro")"
		nota "O envio abaixo sai com as credenciais de quem roda, para separar as duas falhas."
	fi

	local chave_kms
	if ! chave_kms="$(aws_ kms describe-key --key-id alias/aws/s3 2>"$erro" |
		jq -er .KeyMetadata.Arn)"; then
		falha "kms:DescribeKey em alias/aws/s3: $(resumo_do_erro "$erro")"
		return 1
	fi
	ok "chave gerenciada aws/s3 encontrada"

	BUCKET_SONDAGEM="sgs-lab-sondagem-$(aleatorio_hex)"
	if ! aws_ s3api create-bucket --bucket "$BUCKET_SONDAGEM" >/dev/null 2>"$erro"; then
		falha "s3:CreateBucket: $(resumo_do_erro "$erro")"
		BUCKET_SONDAGEM=""
		return 1
	fi
	aws_ s3api put-bucket-tagging --bucket "$BUCKET_SONDAGEM" \
		--tagging "TagSet=[{Key=${ETIQUETA_CHAVE},Value=${ETIQUETA_VALOR}}]" >/dev/null 2>"$erro" ||
		nota "sem etiqueta no bucket temporário: $(resumo_do_erro "$erro")"
	ok "bucket temporário $BUCKET_SONDAGEM criado"

	local corpo resposta esperado
	corpo="$temp/sondagem.txt"
	printf 'sondagem do laboratório sgs (005/T13) %s\n' "$(date -u +%FT%TZ)" >"$corpo"
	esperado="$(sha256_base64 "$corpo")"
	if resposta="$(
		if ((assumiu)); then
			AWS_ACCESS_KEY_ID="$(jq -r .Credentials.AccessKeyId <<<"$credenciais")"
			AWS_SECRET_ACCESS_KEY="$(jq -r .Credentials.SecretAccessKey <<<"$credenciais")"
			AWS_SESSION_TOKEN="$(jq -r .Credentials.SessionToken <<<"$credenciais")"
			export AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
			unset AWS_PROFILE
		fi
		aws_ s3api put-object --bucket "$BUCKET_SONDAGEM" --key reports/sondagem.txt \
			--body "$corpo" --server-side-encryption aws:kms --ssekms-key-id "$chave_kms" \
			--checksum-algorithm SHA256 2>"$erro"
	)"; then
		local sse chave_gravada soma
		sse="$(jq -r '.ServerSideEncryption // ""' <<<"$resposta")"
		chave_gravada="$(jq -r '.SSEKMSKeyId // ""' <<<"$resposta")"
		soma="$(jq -r '.ChecksumSHA256 // ""' <<<"$resposta")"
		if [[ "$sse" == "aws:kms" && "$chave_gravada" == "$chave_kms" && "$soma" == "$esperado" ]]; then
			ok "s3:PutObject com aws:kms (aws/s3) e SHA-256 conferidos na resposta"
		else
			falhas=$((falhas + 1))
			falha "s3:PutObject gravou, mas a resposta não confere (R2.8):"
			[[ "$sse" == "aws:kms" ]] || nota "ServerSideEncryption = '$sse', esperado aws:kms"
			[[ "$chave_gravada" == "$chave_kms" ]] ||
				nota "SSEKMSKeyId = '$(mascarar <<<"$chave_gravada")', esperado a chave aws/s3"
			[[ "$soma" == "$esperado" ]] || nota "ChecksumSHA256 = '$soma', esperado '$esperado'"
		fi
	else
		falhas=$((falhas + 1))
		falha "s3:PutObject com aws:kms: $(resumo_do_erro "$erro")"
	fi

	echo
	if ((falhas == 0)); then
		ok "caminho: AssumeRole (S3_ASSUME_ROLE_ARN = ARN da ${PAPEL_DO_LAB}), sem mudar o código"
		return 0
	fi
	if ((assumiu == 0)); then
		falha "caminho: emenda (fora de prod, sem papel e sem chave fixa, a cadeia padrão do ambiente)"
		nota "Decisão do dono antes do código (spec 005, T13, primeira hora)."
	else
		falha "o AssumeRole passou, mas o envio não: ver as linhas acima"
	fi
	return 1
}

limpar_sondagem() {
	[[ -n "${BUCKET_SONDAGEM:-}" ]] || return 0
	local versoes chave versao
	versoes="$(aws_ s3api list-object-versions --bucket "$BUCKET_SONDAGEM" 2>/dev/null |
		jq -r '(.Versions // []) + (.DeleteMarkers // []) | .[] | "\(.Key)\t\(.VersionId)"')" || true
	while IFS=$'\t' read -r chave versao; do
		[[ -n "$chave" ]] || continue
		aws_ s3api delete-object --bucket "$BUCKET_SONDAGEM" --key "$chave" \
			--version-id "$versao" >/dev/null 2>&1 || true
	done <<<"$versoes"
	if aws_ s3api delete-bucket --bucket "$BUCKET_SONDAGEM" >/dev/null 2>&1; then
		ok "bucket temporário $BUCKET_SONDAGEM apagado"
	else
		falha "não consegui apagar o bucket temporário $BUCKET_SONDAGEM: apague pelo console"
	fi
	BUCKET_SONDAGEM=""
}

# --- recursos do laboratório, achados pela etiqueta -----------------------------------------------

# Etiquetas para --tag-specifications: tipo do recurso e, opcional, etiquetas a mais.
etiquetas() {
	printf 'ResourceType=%s,Tags=[{Key=%s,Value=%s}%s]' "$1" "$ETIQUETA_CHAVE" "$ETIQUETA_VALOR" "${2:-}"
}

exigir_credenciais() {
	local identidade
	if ! identidade="$(aws_ sts get-caller-identity)"; then
		falha "sem credenciais válidas na cadeia padrão do AWS CLI"
		nota "Copie o bloco de 'AWS Details' do Learner Lab para ~/.aws/credentials (o lab dura ~4 h)."
		return 1
	fi
	CONTA="$(jq -r .Account <<<"$identidade")"
}

# A instância que não foi encerrada (JSON), ou nada.
instancia_do_lab() {
	aws_ ec2 describe-instances --filters "$FILTRO_ETIQUETA" \
		"Name=instance-state-name,Values=pending,running,stopping,stopped" |
		jq -c '[.Reservations[].Instances[]][0] // empty'
}

ip_do_lab() { aws_ ec2 describe-addresses --filters "$FILTRO_ETIQUETA" | jq -c '.Addresses[0] // empty'; }

grupo_do_lab() {
	aws_ ec2 describe-security-groups --filters "$FILTRO_ETIQUETA" "Name=group-name,Values=$NOME_DO_GRUPO" |
		jq -c '.SecurityGroups[0] // empty'
}

bucket_do_lab() { aws_ s3api list-buckets --prefix "$PREFIXO_DO_BUCKET" | jq -r '.Buckets[0].Name // empty'; }

host_do_ip() { printf '%s.sslip.io' "${1//./-}"; }

# CIDRs que podem abrir a 443, um por linha: SGS_LAB_IPS ou o IP de quem roda. Faixas maiores que
# /16 são recusadas: a 443 nunca abre para todos (as senhas de laboratório estão no README).
ips_liberados() {
	local lista cidr
	local -a faixas
	lista="${SGS_LAB_IPS:-}"
	if [[ -z "$lista" ]]; then
		lista="$(curl -fsS --max-time 10 https://checkip.amazonaws.com | tr -d '[:space:]')/32"
	fi
	IFS=',' read -ra faixas <<<"$lista"
	for cidr in "${faixas[@]}"; do
		if [[ ! "$cidr" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}/([0-9]|[12][0-9]|3[0-2])$ ]] || ((${cidr#*/} < 16)); then
			falha "faixa recusada para a 443: '$cidr' (use IPs da equipe, de /16 a /32)" >&2
			return 1
		fi
	done
	printf '%s\n' "${faixas[@]}"
}

# Troca as faixas da 443 do grupo GRUPO_ID pelas de $1. $2 é o JSON atual do grupo (ou vazio).
aplicar_443() {
	local cidrs="$1" atual="${2:-}" antigas novas
	if [[ -n "$atual" ]]; then
		antigas="$(jq -c '[.IpPermissions[] | select(.FromPort == 443 and .ToPort == 443)]' <<<"$atual")"
		if [[ "$antigas" != "[]" ]]; then
			aws_ ec2 revoke-security-group-ingress --group-id "$GRUPO_ID" --ip-permissions "$antigas" >/dev/null
		fi
	fi
	novas="$(jq -cRn '[{IpProtocol: "tcp", FromPort: 443, ToPort: 443,
		IpRanges: [inputs | select(length > 0) | {CidrIp: ., Description: "Equipe"}]}]' <<<"$cidrs")"
	aws_ ec2 authorize-security-group-ingress --group-id "$GRUPO_ID" --ip-permissions "$novas" >/dev/null
}

preparar_grupo() {
	local cidrs="$1" grupo vpc prefixos permissoes
	grupo="$(grupo_do_lab)"
	if [[ -n "$grupo" ]]; then
		GRUPO_ID="$(jq -r .GroupId <<<"$grupo")"
		aplicar_443 "$cidrs" "$grupo"
		ok "grupo de segurança $GRUPO_ID reaproveitado, 443 atualizada"
		return
	fi
	vpc="$(aws_ ec2 describe-vpcs --filters Name=isDefault,Values=true | jq -er '.Vpcs[0].VpcId')"
	GRUPO_ID="$(aws_ ec2 create-security-group --group-name "$NOME_DO_GRUPO" \
		--description "Laboratorio sgs-api (005/T13)" --vpc-id "$vpc" \
		--tag-specifications "$(etiquetas security-group)" | jq -er .GroupId)"
	prefixos="$(aws_ ec2 describe-managed-prefix-lists \
		--filters "Name=prefix-list-name,Values=com.amazonaws.${REGIAO}.ec2-instance-connect" |
		jq -er '.PrefixLists[0].PrefixListId')"
	# A 80 abre para todos só para o redirecionamento e o desafio HTTP-01 do Let's Encrypt.
	permissoes="$(jq -cn --arg pl "$prefixos" '[
		{IpProtocol: "tcp", FromPort: 80, ToPort: 80,
		 IpRanges: [{CidrIp: "0.0.0.0/0", Description: "HTTP: redirecionamento e desafio ACME"}]},
		{IpProtocol: "tcp", FromPort: 22, ToPort: 22,
		 PrefixListIds: [{PrefixListId: $pl, Description: "EC2 Instance Connect"}]}]')"
	aws_ ec2 authorize-security-group-ingress --group-id "$GRUPO_ID" --ip-permissions "$permissoes" >/dev/null
	aplicar_443 "$cidrs"
	ok "grupo de segurança $GRUPO_ID: 80 aberta, 443 só da lista, 22 só do EC2 Instance Connect"
}

# Política do bucket como na T7 (docs/architecture/aws-iam-exemplo.md § 3): nega sem TLS e nega
# PutObject sem aws:kms (valor errado ou cabeçalho ausente).
politica_do_bucket() {
	jq -cn --arg b "$1" '{Version: "2012-10-17", Statement: [
		{Sid: "NegaSemTLS", Effect: "Deny", Principal: "*", Action: "s3:*",
		 Resource: ["arn:aws:s3:::\($b)", "arn:aws:s3:::\($b)/*"],
		 Condition: {Bool: {"aws:SecureTransport": "false"}}},
		{Sid: "NegaPutSemKmsValorErrado", Effect: "Deny", Principal: "*", Action: "s3:PutObject",
		 Resource: "arn:aws:s3:::\($b)/*",
		 Condition: {StringNotEquals: {"s3:x-amz-server-side-encryption": "aws:kms"}}},
		{Sid: "NegaPutSemKmsCabecalhoAusente", Effect: "Deny", Principal: "*", Action: "s3:PutObject",
		 Resource: "arn:aws:s3:::\($b)/*",
		 Condition: {Null: {"s3:x-amz-server-side-encryption": "true"}}}]}'
}

# Guarda de 90 dias em reports/ (G1). No laboratório, as versões anteriores expiram em 1 dia e os
# marcadores órfãos somem (responde, só aqui, o ponto 1 de § 8 do documento da T7).
ciclo_de_vida() {
	jq -cn --argjson dias "$RETENCAO_DIAS" '{Rules: [
		{ID: "sgs-relatorios-90-dias", Status: "Enabled", Filter: {Prefix: "reports/"},
		 Expiration: {Days: $dias}, NoncurrentVersionExpiration: {NoncurrentDays: 1},
		 AbortIncompleteMultipartUpload: {DaysAfterInitiation: 1}},
		{ID: "sgs-marcadores-orfaos", Status: "Enabled", Filter: {Prefix: "reports/"},
		 Expiration: {ExpiredObjectDeleteMarker: true}}]}'
}

preparar_bucket() {
	local chave_kms="$1"
	BUCKET="$(bucket_do_lab)"
	if [[ -n "$BUCKET" ]]; then
		nota "bucket $BUCKET reaproveitado"
	else
		BUCKET="${PREFIXO_DO_BUCKET}$(aleatorio_hex)"
		if [[ "$REGIAO" == "us-east-1" ]]; then
			aws_ s3api create-bucket --bucket "$BUCKET" >/dev/null
		else
			aws_ s3api create-bucket --bucket "$BUCKET" \
				--create-bucket-configuration "LocationConstraint=$REGIAO" >/dev/null
		fi
	fi
	aws_ s3api put-bucket-tagging --bucket "$BUCKET" \
		--tagging "TagSet=[{Key=${ETIQUETA_CHAVE},Value=${ETIQUETA_VALOR}}]"
	aws_ s3api put-public-access-block --bucket "$BUCKET" --public-access-block-configuration \
		BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
	aws_ s3api put-bucket-versioning --bucket "$BUCKET" --versioning-configuration Status=Enabled
	aws_ s3api put-bucket-encryption --bucket "$BUCKET" --server-side-encryption-configuration \
		"$(jq -cn --arg k "$chave_kms" \
			'{Rules: [{ApplyServerSideEncryptionByDefault: {SSEAlgorithm: "aws:kms", KMSMasterKeyID: $k}}]}')"
	aws_ s3api put-bucket-policy --bucket "$BUCKET" --policy "$(politica_do_bucket "$BUCKET")"
	aws_ s3api put-bucket-lifecycle-configuration --bucket "$BUCKET" \
		--lifecycle-configuration "$(ciclo_de_vida)"
	ok "bucket $BUCKET: privado, versionado, aws:kms (aws/s3), TLS obrigatório, guarda de ${RETENCAO_DIAS} dias"
}

preparar_ip() {
	local ip
	ip="$(ip_do_lab)"
	if [[ -z "$ip" ]]; then
		ip="$(aws_ ec2 allocate-address --domain vpc \
			--tag-specifications "$(etiquetas elastic-ip ',{Key=Name,Value=sgs-lab}')")"
	fi
	ALOCACAO="$(jq -r .AllocationId <<<"$ip")"
	IP_PUBLICO="$(jq -r .PublicIp <<<"$ip")"
	ok "IP elástico $IP_PUBLICO"
}

# Troca os marcadores do user-data (SGS_LAB_* entre dois sublinhados). Falha se sobrar algum.
renderizar_user_data() {
	SGS_LAB_REPOSITORIO="$REPOSITORIO" SGS_LAB_COMMIT="$1" SGS_LAB_REGIAO="$REGIAO" \
		SGS_LAB_BUCKET="$BUCKET" SGS_LAB_PAPEL_ARN="arn:aws:iam::${CONTA}:role/${PAPEL_DO_LAB}" \
		SGS_LAB_EXTERNAL_ID="$2" SGS_LAB_CHAVE_KMS_ARN="$3" SGS_LAB_HOST="$(host_do_ip "$IP_PUBLICO")" \
		python3 -I - "$RAIZ/docker/aws/user-data.sh" "$4" <<-'PY'
			import os, sys
			texto = open(sys.argv[1], encoding="utf-8").read()
			for nome in ("REPOSITORIO", "COMMIT", "REGIAO", "BUCKET", "PAPEL_ARN", "EXTERNAL_ID",
			             "CHAVE_KMS_ARN", "HOST"):
			    texto = texto.replace(f"__SGS_LAB_{nome}__", os.environ[f"SGS_LAB_{nome}"])
			if "__SGS_LAB_" in texto:
			    sys.exit("user-data: sobrou marcador sem valor")
			with open(sys.argv[2], "w", encoding="utf-8") as saida:
			    saida.write(texto)
		PY
}

# --- subir ----------------------------------------------------------------------------------------

subir() {
	precisa aws jq git python3 od curl
	local temp
	temp="$(mktemp -d)"
	# shellcheck disable=SC2064 # o caminho da pasta é fixado agora, de propósito
	trap "rm -rf '$temp'" EXIT
	exigir_credenciais

	local existente
	existente="$(instancia_do_lab)"
	if [[ -n "$existente" ]]; then
		falha "já existe a instância $(jq -r '"\(.InstanceId) (\(.State.Name))"' <<<"$existente")"
		nota "Use 'lab.sh estado', 'lab.sh ligar' ou, para recomeçar, 'lab.sh destruir --confirmo'."
		return 1
	fi

	local commit
	commit="${SGS_LAB_COMMIT:-$(git -C "$RAIZ" rev-parse HEAD)}"
	if [[ -z "$(git -C "$RAIZ" branch -r --contains "$commit" 2>/dev/null)" ]]; then
		falha "o commit ${commit:0:12} não está em nenhum ramo remoto conhecido, e a instância clona do GitHub"
		nota "Faça o push (ou 'git fetch'), ou defina SGS_LAB_COMMIT com um commit publicado."
		return 1
	fi
	local cidrs
	cidrs="$(ips_liberados)"
	ok "commit ${commit:0:12}; 443 liberada para: $(paste -sd' ' <<<"$cidrs")"

	local ami chave_kms external_id
	ami="$(aws_ ssm get-parameter --name "$PARAMETRO_AMI" | jq -er .Parameter.Value)"
	chave_kms="$(aws_ kms describe-key --key-id alias/aws/s3 | jq -er .KeyMetadata.Arn)"
	ok "imagem Ubuntu 24.04 $ami; chave gerenciada aws/s3"

	preparar_grupo "$cidrs"
	preparar_bucket "$chave_kms"
	preparar_ip

	external_id="sgs-lab-$(aleatorio_hex)"
	renderizar_user_data "$commit" "$external_id" "$chave_kms" "$temp/user-data.sh"

	local instancia
	instancia="$(aws_ ec2 run-instances --image-id "$ami" --instance-type "$TIPO" --count 1 \
		--iam-instance-profile "Name=$PERFIL_DA_INSTANCIA" --security-group-ids "$GRUPO_ID" \
		--user-data "file://$temp/user-data.sh" \
		--metadata-options HttpTokens=required,HttpPutResponseHopLimit=2,HttpEndpoint=enabled \
		--credit-specification CpuCredits=standard \
		--block-device-mappings "[{\"DeviceName\":\"/dev/sda1\",\"Ebs\":{\"VolumeSize\":${DISCO_GIB},\"VolumeType\":\"gp3\",\"Encrypted\":true,\"DeleteOnTermination\":true}}]" \
		--tag-specifications \
		"$(etiquetas instance ",{Key=Name,Value=sgs-lab},{Key=SgsBucket,Value=${BUCKET}}")" \
		"$(etiquetas volume)" |
		jq -er '.Instances[0].InstanceId')"
	ok "instância $instancia ($TIPO, $DISCO_GIB GiB gp3, $PERFIL_DA_INSTANCIA) criada; esperando ligar"
	aws_ ec2 wait instance-running --instance-ids "$instancia"
	aws_ ec2 associate-address --instance-id "$instancia" --allocation-id "$ALOCACAO" >/dev/null
	ok "IP elástico associado"

	local host
	host="$(host_do_ip "$IP_PUBLICO")"
	echo
	ok "subindo: o compose leva de 10 a 15 minutos. Acompanhe com 'lab.sh estado'."
	nota "Sistema:  https://${host}/"
	nota "Keycloak: https://keycloak.${host}/"
	nota "Senhas do administrador e do seed: EC2 Instance Connect, 'sudo cat /opt/sgs/credenciais-do-lab'."
}

# --- estado ---------------------------------------------------------------------------------------

estado() {
	precisa aws jq
	exigir_credenciais
	local instancia ip grupo bucket situacao host
	instancia="$(instancia_do_lab)"
	ip="$(ip_do_lab)"
	grupo="$(grupo_do_lab)"
	bucket="$(bucket_do_lab)"

	if [[ -z "$instancia" ]]; then
		nota "nenhuma instância do laboratório (use 'lab.sh subir')"
	else
		situacao="$(jq -r .State.Name <<<"$instancia")"
		ok "instância $(jq -r '"\(.InstanceId), \(.InstanceType)"' <<<"$instancia"): $situacao"
	fi
	if [[ -n "$ip" ]]; then
		host="$(host_do_ip "$(jq -r .PublicIp <<<"$ip")")"
		ok "IP elástico $(jq -r .PublicIp <<<"$ip")"
		nota "Sistema:  https://${host}/"
		nota "Keycloak: https://keycloak.${host}/"
	fi
	if [[ -n "$grupo" ]]; then
		ok "443 liberada para: $(jq -r '[.IpPermissions[] | select(.FromPort == 443) | .IpRanges[].CidrIp] | join(" ")' <<<"$grupo")"
	fi
	[[ -z "$bucket" ]] || ok "bucket $bucket"

	if [[ "${situacao:-}" == "running" ]]; then
		echo
		nota "progresso da subida (console da instância, pode atrasar alguns minutos):"
		aws_ ec2 get-console-output --instance-id "$(jq -r .InstanceId <<<"$instancia")" --latest |
			jq -r '.Output // ""' | grep -o 'sgs-lab: .*' | tail -n 40 | mascarar || true
	fi
}

# --- liberar-ip, parar, ligar ---------------------------------------------------------------------

liberar_ip() {
	precisa aws jq curl
	exigir_credenciais
	local grupo cidrs
	grupo="$(grupo_do_lab)"
	if [[ -z "$grupo" ]]; then
		falha "não há grupo de segurança do laboratório (use 'lab.sh subir')"
		return 1
	fi
	cidrs="$(ips_liberados)"
	GRUPO_ID="$(jq -r .GroupId <<<"$grupo")"
	aplicar_443 "$cidrs" "$grupo"
	ok "443 liberada para: $(paste -sd' ' <<<"$cidrs")"
}

instancia_ou_falha() {
	local instancia
	instancia="$(instancia_do_lab)"
	if [[ -z "$instancia" ]]; then
		falha "nenhuma instância do laboratório (use 'lab.sh subir')" >&2
		return 1
	fi
	jq -r .InstanceId <<<"$instancia"
}

parar() {
	precisa aws jq
	exigir_credenciais
	local instancia
	instancia="$(instancia_ou_falha)"
	aws_ ec2 stop-instances --instance-ids "$instancia" >/dev/null
	ok "instância $instancia parando; os dados e o IP elástico ficam"
}

ligar() {
	precisa aws jq
	exigir_credenciais
	local instancia ip
	instancia="$(instancia_ou_falha)"
	aws_ ec2 start-instances --instance-ids "$instancia" >/dev/null
	aws_ ec2 wait instance-running --instance-ids "$instancia"
	ok "instância $instancia ligada; o compose volta sozinho em alguns minutos"
	ip="$(ip_do_lab)"
	[[ -z "$ip" ]] || nota "Sistema: https://$(host_do_ip "$(jq -r .PublicIp <<<"$ip")")/"
}

# --- destruir -------------------------------------------------------------------------------------

esvaziar_bucket() {
	local lote
	while :; do
		lote="$(aws_ s3api list-object-versions --bucket "$1" --max-items 1000 |
			jq -c '{Objects: [((.Versions // []) + (.DeleteMarkers // []))[] | {Key, VersionId}], Quiet: true}')"
		[[ "$(jq '.Objects | length' <<<"$lote")" -gt 0 ]] || break
		aws_ s3api delete-objects --bucket "$1" --delete "$lote" >/dev/null
	done
}

destruir() {
	if [[ "${1:-}" != "--confirmo" ]]; then
		falha "destruir apaga a instância, o IP, o bucket com todos os relatórios e o grupo de segurança"
		nota "Para seguir: lab.sh destruir --confirmo"
		return 1
	fi
	precisa aws jq
	exigir_credenciais
	local instancia ip bucket grupo tentativa
	instancia="$(instancia_do_lab)"
	if [[ -n "$instancia" ]]; then
		instancia="$(jq -r .InstanceId <<<"$instancia")"
		aws_ ec2 terminate-instances --instance-ids "$instancia" >/dev/null
		aws_ ec2 wait instance-terminated --instance-ids "$instancia"
		ok "instância $instancia encerrada"
	fi
	ip="$(ip_do_lab)"
	if [[ -n "$ip" ]]; then
		aws_ ec2 release-address --allocation-id "$(jq -r .AllocationId <<<"$ip")"
		ok "IP elástico $(jq -r .PublicIp <<<"$ip") liberado"
	fi
	bucket="$(bucket_do_lab)"
	if [[ -n "$bucket" ]]; then
		esvaziar_bucket "$bucket"
		aws_ s3api delete-bucket --bucket "$bucket"
		ok "bucket $bucket apagado, com todas as versões"
	fi
	grupo="$(grupo_do_lab)"
	if [[ -n "$grupo" ]]; then
		# A interface de rede da instância encerrada pode levar alguns segundos para soltar o grupo.
		for tentativa in 1 2 3 4 5 6; do
			if aws_ ec2 delete-security-group --group-id "$(jq -r .GroupId <<<"$grupo")" 2>/dev/null; then
				ok "grupo de segurança apagado"
				break
			fi
			((tentativa < 6)) || {
				falha "não consegui apagar o grupo de segurança: apague pelo console"
				return 1
			}
			sleep "${SGS_LAB_ESPERA:-10}"
		done
	fi
	ok "nada do laboratório ficou na conta"
}

# --- entrada --------------------------------------------------------------------------------------

principal() {
	local subcomando="${1:-}"
	shift || true
	case "$subcomando" in
	sondar) sondar ;;
	subir) subir ;;
	estado) estado ;;
	liberar-ip) liberar_ip ;;
	parar) parar ;;
	ligar) ligar ;;
	destruir) destruir "$@" ;;
	*)
		uso
		exit 2
		;;
	esac
}

principal "$@"
