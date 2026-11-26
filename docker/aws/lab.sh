#!/usr/bin/env bash
# Laboratório das specs 004 e 005 numa conta AWS Academy Learner Lab (spec 005, T13).
#
# Credenciais: só pela cadeia padrão do AWS CLI (~/.aws/credentials, variáveis AWS_* ou o perfil
# da instância). Nunca por argumento, nunca no repositório. A saída não mostra segredo nem id da
# conta: números de 12 dígitos saem como <ID_DA_CONTA>.
#
# Uso: docker/aws/lab.sh <subcomando>
#   sondar   confere se a LabRole consegue assumir a LabRole (sts:AssumeRole com ExternalId,
#            900 s) e se um PutObject com aws:kms na chave aws/s3 passa, num bucket temporário
#            que é apagado no fim. Sai com 0 se o caminho de envio da 005/T3 serve sem mudança.
set -euo pipefail

REGIAO="${AWS_REGION:-${AWS_DEFAULT_REGION:-us-east-1}}"
ETIQUETA_CHAVE="Projeto"
ETIQUETA_VALOR="sgs-lab"
PAPEL_DO_LAB="LabRole"
EXTERNAL_ID_SONDAGEM="sgs-lab-sondagem"

uso() {
	cat >&2 <<-'FIM'
		uso: docker/aws/lab.sh <subcomando>
		  sondar   confere AssumeRole na LabRole e PutObject com aws:kms (bucket temporário)
	FIM
}

ok() { printf 'OK     %s\n' "$*"; }
falha() { printf 'FALHA  %s\n' "$*"; }
nota() { printf '       %s\n' "$*"; }

# Tira o id da conta (12 dígitos) de qualquer texto que vá para a tela.
mascarar() { sed -E 's/(^|[^0-9])[0-9]{12}([^0-9]|$)/\1<ID_DA_CONTA>\2/g'; }

# Primeira linha útil de um erro do AWS CLI, sem o id da conta.
resumo_do_erro() { grep -m1 -E '[^[:space:]]' "$1" | mascarar; }

aws_() { aws --region "$REGIAO" --output json "$@"; }

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
	ok "identidade: $(mascarar <<<"$quem") (região $REGIAO)"
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

# --- entrada --------------------------------------------------------------------------------------

principal() {
	case "${1:-}" in
	sondar) sondar ;;
	*)
		uso
		exit 2
		;;
	esac
}

principal "$@"
