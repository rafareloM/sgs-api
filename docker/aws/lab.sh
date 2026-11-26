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
#   SGS_LAB_TIPO        tipo da instância (padrão: t3.small, com créditos de CPU unlimited)
#   SGS_LAB_REPOSITORIO repositório que a instância clona
#   SGS_LAB_SENHA_ADMIN_ARQUIVO  senha do admin do lab, para a evidência (padrão: ~/.config/sgs-lab/senha-admin)
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
		  evidencia            confere o laboratório no ar e grava docs/operacao/evidencias/laboratorio-aws-<data>.json
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
		--tagging "TagSet=[{Key=${ETIQUETA_CHAVE},Value=${ETIQUETA_VALOR}}]" >/dev/null
	aws_ s3api put-public-access-block --bucket "$BUCKET" --public-access-block-configuration \
		BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
	aws_ s3api put-bucket-versioning --bucket "$BUCKET" --versioning-configuration Status=Enabled
	aws_ s3api put-bucket-encryption --bucket "$BUCKET" --server-side-encryption-configuration \
		"$(jq -cn --arg k "$chave_kms" \
			'{Rules: [{ApplyServerSideEncryptionByDefault: {SSEAlgorithm: "aws:kms", KMSMasterKeyID: $k}}]}')"
	aws_ s3api put-bucket-policy --bucket "$BUCKET" --policy "$(politica_do_bucket "$BUCKET")"
	aws_ s3api put-bucket-lifecycle-configuration --bucket "$BUCKET" \
		--lifecycle-configuration "$(ciclo_de_vida)" >/dev/null
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
		--credit-specification CpuCredits=unlimited \
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

# --- evidencia ------------------------------------------------------------------------------------
# Roda do computador de quem demonstra (o IP dele está na lista da 443), contra o laboratório no ar.
# Só bash, curl, jq, python3 e AWS CLI. Nenhum token, senha ou URL assinada vai para a tela ou
# para o arquivo de evidência; os tokens vão para o curl por arquivo (-H @arquivo), não pela
# linha de comando.

CONFIG_DO_LAB="${SGS_LAB_CONFIG:-${XDG_CONFIG_HOME:-$HOME/.config}/sgs-lab}"
SENHA_DE_EXEMPLO_DO_LAB="sgs-lab-exemplo-usuario"

# Código TOTP (RFC 6238: SHA-1, 6 dígitos, 30 s) de uma URI otpauth://, só com a biblioteca padrão.
# O segundo argumento, opcional, fixa o instante (usado nos testes).
totp() {
	python3 -I - "$@" <<-'PY'
		import base64, hashlib, hmac, struct, sys, time, urllib.parse as u
		segredo = u.parse_qs(u.urlsplit(sys.argv[1]).query)["secret"][0].upper()
		chave = base64.b32decode(segredo + "=" * (-len(segredo) % 8))
		instante = int(sys.argv[2]) if len(sys.argv) > 2 else int(time.time())
		resumo = hmac.new(chave, struct.pack(">Q", instante // 30), hashlib.sha1).digest()
		inicio = resumo[-1] & 0x0F
		numero = struct.unpack(">I", resumo[inicio:inicio + 4])[0] & 0x7FFFFFFF
		print(f"{numero % 1_000_000:06d}")
	PY
}

# Tira do texto da evidência o id da conta, o IP do laboratório (com pontos ou traços) e qualquer
# parâmetro de assinatura que escape por engano.
sanitizar_evidencia() {
	local ip="$1" tracos
	tracos="${ip//./-}"
	mascarar | sed -E \
		-e "s/${ip//./\\.}/<IP_DO_LAB>/g" \
		-e "s/${tracos}/<IP_DO_LAB>/g" \
		-e 's/X-Amz-[A-Za-z-]+=[^&"]*/X-Amz-<OMITIDO>/g'
}

# Chamada à API do laboratório. Imprime o corpo; o status HTTP fica em "$TEMP_EV/status".
# $1 método, $2 caminho (sem /api/v1), $3 corpo JSON opcional, $4 arquivo de autorização opcional.
api_lab() {
	local -a args=(-sS -X "$1" -o "$TEMP_EV/resposta" -w '%{http_code}' -c "$JARRO" -b "$JARRO"
		-H 'Accept: application/json')
	if [[ -n "${3:-}" ]]; then
		printf '%s' "$3" >"$TEMP_EV/corpo"
		args+=(-H 'Content-Type: application/json' --data-binary "@$TEMP_EV/corpo")
	fi
	[[ -z "${4:-}" ]] || args+=(-H "@$4")
	curl "${args[@]}" "https://${HOST_EV}/api/v1$2" >"$TEMP_EV/status" || echo 000 >"$TEMP_EV/status"
	rm -f "$TEMP_EV/corpo"
	cat "$TEMP_EV/resposta"
}

status_http() { cat "$TEMP_EV/status"; }

# Guarda o access token num arquivo de cabeçalho e devolve o caminho.
cabecalho_de() {
	local arquivo="$TEMP_EV/aut-$1"
	(
		umask 077
		printf 'Authorization: Bearer %s\n' "$2" >"$arquivo"
	)
	printf '%s' "$arquivo"
}

# Login da spec 002 com 2FA. Cadastra o 2FA no primeiro acesso e guarda a URI em
# $CONFIG_DO_LAB/<usuario>.totp (0600), para os acessos seguintes. Imprime o access token.
entrar() {
	local usuario="$1" senha="$2" provedor="$3" login desafio uri arquivo_uri corpo
	arquivo_uri="$CONFIG_DO_LAB/${usuario}.totp"
	corpo="$(jq -cn --arg u "$usuario" --arg p "$senha" --arg pr "$provedor" \
		'{username: $u, password: $p, provider: $pr}')"
	login="$(api_lab POST /auth/login "$corpo")"
	if [[ "$(status_http)" != 200 ]]; then
		falha "login de $usuario ($provedor): HTTP $(status_http)" >&2
		return 1
	fi
	desafio="$(jq -r .mfa_token <<<"$login")"
	if [[ "$(jq -r .mfa_enrollment_required <<<"$login")" == "true" ]]; then
		uri="$(api_lab POST /auth/mfa/enroll "$(jq -cn --arg t "$desafio" '{mfa_token: $t}')" | jq -r .otpauth_uri)"
		(
			umask 077
			mkdir -p "$CONFIG_DO_LAB"
			printf '%s\n' "$uri" >"$arquivo_uri"
		)
		api_lab POST /auth/mfa/confirm \
			"$(jq -cn --arg t "$desafio" --arg c "$(totp "$uri")" '{mfa_token: $t, code: $c}')" |
			jq -r .access_token
	elif [[ -s "$arquivo_uri" ]]; then
		api_lab POST /auth/mfa/verify \
			"$(jq -cn --arg t "$desafio" --arg c "$(totp "$(cat "$arquivo_uri")")" '{mfa_token: $t, code: $c}')" |
			jq -r .access_token
	else
		falha "$usuario já tem 2FA, mas não há $arquivo_uri: não consigo gerar o código" >&2
		return 1
	fi
}

# Login OIDC sem navegador: início na API, formulário do Keycloak, callback e renovação pelo
# cookie de refresh (com o anti-CSRF da 002). Imprime um JSON com o resultado e o access token.
entrar_oidc() {
	local usuario="$1" jarro_oidc="$TEMP_EV/jarro-oidc" pagina acao volta destino token
	rm -f "$jarro_oidc"
	local -a curl_oidc=(-sS -c "$jarro_oidc" -b "$jarro_oidc")
	pagina="$(curl "${curl_oidc[@]}" -o /dev/null -w '%{redirect_url}' "https://${HOST_EV}/api/v1/auth/oidc/login")"
	if [[ "$pagina" != "https://keycloak.${HOST_EV}/"* ]]; then
		jq -cn '{inicio_vai_ao_keycloak: false}'
		return 0
	fi
	acao="$(curl "${curl_oidc[@]}" "$pagina" | python3 -I -c '
import html, re, sys
achado = re.search(r"<form[^>]*id=\"kc-form-login\"[^>]*action=\"([^\"]+)\"", sys.stdin.read())
print(html.unescape(achado.group(1)) if achado else "")')"
	volta="$(curl "${curl_oidc[@]}" -o /dev/null -w '%{redirect_url}' \
		--data-urlencode "username=$usuario" --data-urlencode "password=$SENHA_DE_EXEMPLO_DO_LAB" \
		--data-urlencode "credentialId=" "$acao")"
	destino="$(curl "${curl_oidc[@]}" -o /dev/null -w '%{http_code} %{redirect_url}' "$volta")"
	token="$(curl "${curl_oidc[@]}" -X POST -H 'X-Requested-With: sgs' -H "Origin: https://${HOST_EV}" \
		"https://${HOST_EV}/api/v1/auth/refresh" | jq -r '.access_token // empty')"
	jq -cn --arg volta "$volta" --arg destino "$destino" --arg token "$token" --arg host "$HOST_EV" '{
		inicio_vai_ao_keycloak: true,
		keycloak_volta_ao_callback: ($volta | startswith("https://\($host)/api/v1/auth/oidc/callback")),
		callback_status: ($destino | split(" ")[0] | tonumber),
		callback_volta_ao_front_sem_erro: (($destino | split(" ")[1]) == "https://\($host)/"),
		token_pela_renovacao: ($token != ""),
		token: $token}'
}

resumo_do_me() {
	jq -c '{username, origem, papeis: [(.papeis // [])[] | {papel, origem, escopo_tipo}]}'
}

grupo_id() {
	api_lab GET "/admin/diretorio/grupos?origem=$1&busca=$2" "" "$3" |
		jq -r --arg n "$2" '[.itens[] | select(.nome == $n)][0].id // empty'
}

# Mapeia um grupo para GESTOR_DADOS (escopo global), se ainda não estiver mapeado.
mapear_gestor_dados() {
	local grupo="$1" autorizacao="$2"
	if api_lab GET /admin/mapeamentos-grupo "" "$autorizacao" |
		jq -e --arg g "$grupo" '[(.itens // .)[] | select(.grupo_id == $g and .papel == "GESTOR_DADOS")] | length > 0' >/dev/null; then
		return 0
	fi
	api_lab POST /admin/mapeamentos-grupo \
		"$(jq -cn --arg g "$grupo" '{grupo_id: $g, papel: "GESTOR_DADOS", escopo_tipo: "global"}')" \
		"$autorizacao" >/dev/null
	[[ "$(status_http)" == 201 || "$(status_http)" == 200 ]]
}

esperar_status() { # caminho, autorização, jq dos estados finais; imprime o último corpo
	local corpo tentativa
	for tentativa in $(seq 1 "${SGS_LAB_TENTATIVAS:-40}"); do
		corpo="$(api_lab GET "$1" "" "$2")"
		if jq -e "$3" <<<"$corpo" >/dev/null 2>&1; then
			printf '%s' "$corpo"
			return 0
		fi
		((tentativa == 1)) || sleep "${SGS_LAB_ESPERA:-3}"
	done
	printf '%s' "$corpo"
}

evidencia() {
	precisa aws jq curl python3
	exigir_credenciais
	local temp
	temp="$(mktemp -d)"
	# shellcheck disable=SC2064 # o caminho da pasta é fixado agora, de propósito
	trap "rm -rf '$temp'" EXIT
	TEMP_EV="$temp"
	JARRO="$temp/jarro"

	local ip bucket senha_admin arquivo_senha
	ip="$(ip_do_lab)"
	bucket="$(bucket_do_lab)"
	if [[ -z "$ip" || -z "$bucket" ]]; then
		falha "o laboratório não está no ar (use 'lab.sh subir' e 'lab.sh estado')"
		return 1
	fi
	IP_EV="$(jq -r .PublicIp <<<"$ip")"
	HOST_EV="$(host_do_ip "$IP_EV")"
	arquivo_senha="${SGS_LAB_SENHA_ADMIN_ARQUIVO:-$CONFIG_DO_LAB/senha-admin}"
	if [[ ! -s "$arquivo_senha" ]]; then
		falha "falta a senha do administrador do laboratório em $arquivo_senha"
		nota "Ela só existe na instância: EC2 Instance Connect, 'sudo cat /opt/sgs/credenciais-do-lab'."
		nota "Grave só a senha (linha 'admin:') nesse arquivo, com permissão 0600."
		return 1
	fi
	senha_admin="$(head -n1 "$arquivo_senha")"
	local -a falhas=()
	confere() { # descrição, condição jq, json
		if jq -e "$2" <<<"$3" >/dev/null 2>&1; then ok "$1"; else
			falha "$1"
			falhas+=("$1")
		fi
	}

	# 1. TLS público (Let's Encrypt) no endereço do laboratório.
	local tls
	tls="$(python3 -I - "$HOST_EV" <<-'PY'
		import json, socket, ssl, sys
		host = sys.argv[1]
		try:
		    with socket.create_connection((host, 443), timeout=10) as bruto:
		        with ssl.create_default_context().wrap_socket(bruto, server_hostname=host) as tls:
		            emissor = dict(x[0] for x in tls.getpeercert()["issuer"])
		    print(json.dumps({"certificado_confiavel": True, "emissor": emissor.get("organizationName")}))
		except (OSError, ssl.SSLError) as erro:
		    print(json.dumps({"certificado_confiavel": False, "erro": type(erro).__name__}))
	PY
	)"
	confere "TLS público em https://<host>/ (certificado conferido pelas CAs do sistema)" '.certificado_confiavel' "$tls"

	# 2. Administrador local, sincronização LDAP e mapeamentos para GESTOR_DADOS.
	local admin aut_admin execucao sincronizacao grupo_ldap grupo_oidc
	admin="$(entrar admin "$senha_admin" local)" || true
	unset senha_admin
	if [[ -z "$admin" || "$admin" == "null" ]]; then
		falha "login do administrador: sem isso não há sincronização nem mapeamento"
		return 1
	fi
	aut_admin="$(cabecalho_de admin "$admin")"
	execucao="$(api_lab POST /admin/diretorio/sincronizar "" "$aut_admin" | jq -r '.execucao_id // empty')"
	sincronizacao="$(esperar_status "/admin/diretorio/execucoes/$execucao" "$aut_admin" \
		'.status != "pendente" and .status != "em_andamento"' | jq -c '{status, usuarios, grupos, conflitos}')"
	confere "sincronização LDAP concluída (LDAPS, conta de serviço só leitura)" '.status == "concluida"' "$sincronizacao"
	grupo_ldap="$(grupo_id ldap sgs-gestor-dados "$aut_admin")"
	[[ -n "$grupo_ldap" ]] && mapear_gestor_dados "$grupo_ldap" "$aut_admin" || true

	# 3. Login LDAP com 2FA: o papel vem do grupo mapeado.
	local gestor aut_gestor me_ldap
	gestor="$(entrar ldap.gestor.dados "$SENHA_DE_EXEMPLO_DO_LAB" ldap)" || true
	aut_gestor="$(cabecalho_de gestor "${gestor:-}")"
	me_ldap="$(api_lab GET /me "" "$aut_gestor" | resumo_do_me)"
	confere "login LDAP com 2FA de ldap.gestor.dados, com GESTOR_DADOS do grupo mapeado" \
		'[.papeis[] | select(.papel == "GESTOR_DADOS")] | length > 0' "$me_ldap"

	# 4. Login OIDC pelo formulário do Keycloak; o grupo do token é espelhado e mapeado.
	local oidc_1 oidc_2 me_oidc
	oidc_1="$(entrar_oidc oidc.gestor.dados)"
	grupo_oidc="$(grupo_id oidc oidc-gestor-dados "$aut_admin")"
	[[ -n "$grupo_oidc" ]] && mapear_gestor_dados "$grupo_oidc" "$aut_admin" || true
	oidc_2="$(entrar_oidc oidc.gestor.dados)"
	me_oidc="$(api_lab GET /me "" "$(cabecalho_de oidc "$(jq -r .token <<<"$oidc_2")")" | resumo_do_me)"
	confere "login OIDC de oidc.gestor.dados (Keycloak, callback, refresh), sem token na URL" \
		'.inicio_vai_ao_keycloak and .keycloak_volta_ao_callback and .callback_status == 302 and .callback_volta_ao_front_sem_erro and .token_pela_renovacao' "$oidc_2"
	confere "grupo OIDC oidc-gestor-dados espelhado e mapeado: GESTOR_DADOS no /me" \
		'[.papeis[] | select(.papel == "GESTOR_DADOS")] | length > 0' "$me_oidc"

	# 5. Exportação: pedido, geração, envio ao bucket real (AssumeRole, aws:kms, SHA-256).
	local pedido relatorio sha_hex url download sem_assinatura sem_tls
	pedido="$(api_lab POST /relatorios '{"tipo": "inventario_unidades", "formato": "csv"}' "$aut_gestor" | jq -r '.id // empty')"
	relatorio="$(esperar_status "/relatorios/$pedido" "$aut_gestor" \
		'.status == "concluido" or .status == "falhou" or .status == "interrompido"' |
		jq -c '{id, tipo, formato, status, tamanho_bytes, erro, integridade}')"
	confere "relatório exportado para o bucket real (status concluido, com integridade)" \
		'.status == "concluido" and .integridade.sha256 != null' "$relatorio"
	sha_hex="$(jq -r '.integridade.sha256 // ""' <<<"$relatorio")"
	url="$(api_lab GET "/relatorios/$pedido/download" "" "$aut_gestor" | jq -r '.url // empty')"
	download="$(curl -sS -o "$temp/relatorio" -w '%{http_code}' "$url" || echo 000)"
	download="$(jq -cn --arg s "$download" --arg h "$(sha256sum "$temp/relatorio" 2>/dev/null | cut -d' ' -f1)" \
		--arg e "$sha_hex" --arg u "$url" '{status: ($s | tonumber), sha256_confere: ($h == $e),
		url_na_aws: ($u | test("^https://[^/]+\\.s3\\.[a-z0-9-]+\\.amazonaws\\.com/"))}')"
	confere "download pela URL pré-assinada (200) com o SHA-256 da integridade" \
		'.status == 200 and .sha256_confere and .url_na_aws' "$download"
	sem_assinatura="$(curl -sS -o "$temp/sem" -w '%{http_code}' "${url%%\?*}" || echo 000)"
	sem_assinatura="$(jq -cn --arg s "$sem_assinatura" --arg c "$(grep -o '<Code>[^<]*' "$temp/sem" | cut -c7-)" \
		'{status: ($s | tonumber), codigo: $c}')"
	confere "a mesma URL sem a assinatura é recusada (AccessDenied)" \
		'.status == 403 and .codigo == "AccessDenied"' "$sem_assinatura"
	sem_tls="$(curl -sS -o "$temp/http" -w '%{http_code}' "http://${url#https://}" || echo 000)"
	sem_tls="$(jq -cn --arg s "$sem_tls" --arg c "$(grep -o '<Code>[^<]*' "$temp/http" | cut -c7-)" \
		'{status: ($s | tonumber), codigo: $c}')"
	confere "a URL assinada por HTTP, sem TLS, é recusada pela política do bucket" \
		'.status == 403 and .codigo == "AccessDenied"' "$sem_tls"
	# Endereço virtual (bucket no nome do host): o caminho da URL é a chave do objeto.
	local chave_objeto
	chave_objeto="$(python3 -I -c 'import sys, urllib.parse as u; print(u.unquote(u.urlsplit(sys.argv[1]).path.lstrip("/")))' "$url")"
	unset url

	# 6. O objeto gravado, lido de fora da API: aws:kms na chave aws/s3 e o mesmo SHA-256.
	local objeto chave_kms
	chave_kms="$(aws_ kms describe-key --key-id alias/aws/s3 | jq -r .KeyMetadata.Arn)"
	objeto="$(aws_ s3api head-object --bucket "$bucket" --key "$chave_objeto" --checksum-mode ENABLED 2>/dev/null |
		jq -c --arg k "$chave_kms" '{ServerSideEncryption, SSEKMSKeyId, ChecksumSHA256, VersionId,
		chave_e_a_aws_s3: (.SSEKMSKeyId == $k)}' || echo '{}')"
	objeto="$(python3 -I - "$objeto" "$sha_hex" <<-'PY'
		import base64, json, sys
		dados = json.loads(sys.argv[1])
		soma = dados.get("ChecksumSHA256") or ""
		dados["sha256_confere"] = bool(soma) and base64.b64decode(soma).hex() == sys.argv[2]
		print(json.dumps(dados))
	PY
	)"
	confere "objeto no bucket com aws:kms na chave aws/s3 e o mesmo SHA-256 (R2.3, R2.8)" \
		'.ServerSideEncryption == "aws:kms" and .chave_e_a_aws_s3 and .sha256_confere' "$objeto"

	# 7. A política do bucket recusa envio sem aws:kms, mesmo de quem tem s3:PutObject.
	local put_sem_kms
	printf 'evidencia 005/T13\n' >"$temp/sem-kms.txt"
	if aws_ s3api put-object --bucket "$bucket" --key evidencias/sem-kms.txt --body "$temp/sem-kms.txt" \
		>/dev/null 2>"$temp/erro-put"; then
		aws_ s3api delete-object --bucket "$bucket" --key evidencias/sem-kms.txt >/dev/null || true
		put_sem_kms='{"recusado": false}'
	else
		put_sem_kms="$(jq -cn --arg c "$(grep -o '([A-Za-z]*)' "$temp/erro-put" | head -n1 | tr -d '()')" \
			'{recusado: true, codigo: $c}')"
	fi
	confere "PutObject sem aws:kms recusado pela política do bucket" \
		'.recusado and .codigo == "AccessDenied"' "$put_sem_kms"

	# 8. Configuração do bucket.
	local configuracao
	configuracao="$(jq -cn \
		--argjson bloqueio "$(aws_ s3api get-public-access-block --bucket "$bucket" | jq -c .PublicAccessBlockConfiguration)" \
		--argjson versao "$(aws_ s3api get-bucket-versioning --bucket "$bucket")" \
		--argjson cifra "$(aws_ s3api get-bucket-encryption --bucket "$bucket" | jq -c '.ServerSideEncryptionConfiguration.Rules[0].ApplyServerSideEncryptionByDefault')" \
		--argjson ciclo "$(aws_ s3api get-bucket-lifecycle-configuration --bucket "$bucket" | jq -c '[.Rules[] | {ID, Status, Filter, Expiration, NoncurrentVersionExpiration}]')" \
		--argjson politica "$(aws_ s3api get-bucket-policy --bucket "$bucket" | jq -c '.Policy | fromjson | [.Statement[] | {Sid, Effect}]')" \
		'{bloqueio_publico: $bloqueio, versionamento: $versao.Status, criptografia_padrao: $cifra, ciclo_de_vida: $ciclo, politica: $politica}')"
	confere "bucket privado, versionado, aws:kms, guarda de 90 dias e política de TLS e aws:kms" \
		'(.bloqueio_publico | [.[]] | all) and .versionamento == "Enabled" and .criptografia_padrao.SSEAlgorithm == "aws:kms" and (.ciclo_de_vida | any(.Expiration.Days == 90)) and (.politica | length == 3)' "$configuracao"

	# 9. A identidade do envio: o AssumeRole da API no CloudTrail (sessão sgs-<id>, 900 s).
	local assume tentativa
	nota "procurando o AssumeRole da API no CloudTrail (pode levar alguns minutos)..."
	assume='{}'
	for tentativa in $(seq 1 "${SGS_LAB_TENTATIVAS_CLOUDTRAIL:-20}"); do
		assume="$(aws_ cloudtrail lookup-events --max-results 50 \
			--lookup-attributes AttributeKey=EventName,AttributeValue=AssumeRole |
			jq -c '[.Events[].CloudTrailEvent | fromjson
				| select(.requestParameters.roleSessionName // "" | test("^sgs-[0-9a-f-]{36}$"))
				| {papel: (.requestParameters.roleArn | sub(".*:role/"; "")), sessao: .requestParameters.roleSessionName,
				   duracao_s: .requestParameters.durationSeconds, external_id_enviado: (.requestParameters.externalId != null),
				   quem_assumiu: (.userIdentity.arn | sub("/i-[0-9a-f]+$"; "/<INSTANCIA>")), quando: .eventTime}][0] // {}')" ||
			assume='{}'
		[[ "$assume" == "{}" ]] || break
		((tentativa == ${SGS_LAB_TENTATIVAS_CLOUDTRAIL:-20})) || sleep "${SGS_LAB_ESPERA_CLOUDTRAIL:-30}"
	done
	confere "envio com AssumeRole na LabRole, sessão sgs-<id>, 900 s, com ExternalId (R2.1)" \
		'.papel == "LabRole" and .duracao_s == 900 and .external_id_enviado' "$assume"

	# 10. O arquivo da evidência, sem id de conta, sem IP e sem nada assinado.
	local destino commit
	commit="$(aws_ ec2 get-console-output --instance-id "$(jq -r .InstanceId <<<"$(instancia_do_lab)")" 2>/dev/null |
		jq -r '.Output // ""' | grep -o 'código em [^ ]* ([0-9a-f]*)' | tail -n1 | grep -o '([0-9a-f]*)' | tr -d '()' || true)"
	destino="$RAIZ/docs/operacao/evidencias/laboratorio-aws-$(date +%F).json"
	mkdir -p "$(dirname "$destino")"
	jq -n --arg data "$(date -u +%FT%TZ)" --arg regiao "$REGIAO" --arg commit "${commit:-desconhecido}" \
		--arg bucket "$bucket" --argjson falhas "$(printf '%s\n' "${falhas[@]}" | jq -R . | jq -cs 'map(select(length > 0))')" \
		--argjson tls "$tls" --argjson sinc "$sincronizacao" --argjson me_ldap "$me_ldap" \
		--argjson oidc_1 "$(jq -c 'del(.token)' <<<"$oidc_1")" --argjson oidc_2 "$(jq -c 'del(.token)' <<<"$oidc_2")" \
		--argjson me_oidc "$me_oidc" --argjson relatorio "$relatorio" --argjson download "$download" \
		--argjson sem_assinatura "$sem_assinatura" --argjson sem_tls "$sem_tls" --argjson objeto "$objeto" \
		--argjson put "$put_sem_kms" --argjson bucket_cfg "$configuracao" --argjson assume "$assume" '{
		tarefa: "005/T13", gerado_em: $data, regiao: $regiao, commit_da_instancia: $commit,
		conta: "<ID_DA_CONTA> (Learner Lab do AWS Academy)", endereco: "https://<IP_DO_LAB>.sslip.io/",
		resultado: (if ($falhas | length) == 0 then "tudo conferido" else "com falhas" end), falhas: $falhas,
		tls_publico: $tls,
		diretorio: {sincronizacao_ldap: $sinc, login_ldap_2fa: {usuario: "ldap.gestor.dados", me: $me_ldap},
			login_oidc: {usuario: "oidc.gestor.dados", primeiro_acesso: $oidc_1, depois_do_mapeamento: $oidc_2, me: $me_oidc}},
		relatorio: $relatorio,
		s3: {bucket: $bucket, identidade_do_envio: $assume, objeto: $objeto, download_pre_assinado: $download,
			mesma_url_sem_assinatura: $sem_assinatura, url_assinada_por_http: $sem_tls,
			put_sem_kms: $put, configuracao_do_bucket: $bucket_cfg}}' |
		sanitizar_evidencia "$IP_EV" >"$destino"
	echo
	if ((${#falhas[@]} == 0)); then
		ok "evidência gravada em ${destino#"$RAIZ"/}: tudo conferido"
		return 0
	fi
	falha "evidência gravada em ${destino#"$RAIZ"/}, com ${#falhas[@]} falha(s)"
	return 1
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
	evidencia) evidencia ;;
	destruir) destruir "$@" ;;
	*)
		uso
		exit 2
		;;
	esac
}

# Os testes carregam o script com `source` para chamar as funções; só a execução direta roda.
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
	principal "$@"
fi
