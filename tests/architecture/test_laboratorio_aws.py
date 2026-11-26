"""Laboratório na AWS (spec 005, T13): os scripts de `docker/aws/`.

Nada aqui fala com a AWS. O `lab.sh` roda com um `aws` falso no PATH (`_AWS_FALSO`), que responde
como o AWS CLI v2 e anota cada chamada, com as credenciais do ambiente, num arquivo; e com um `git`
falso, que diz se o commit está num ramo remoto. Assim se confere o que o script decide, sem conta
e sem rede. O `docker compose config` da sobreposição roda de verdade (pulado sem Docker).
"""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from src.core.config import load_settings
from src.tools.crypto_keys import novas_chaves
from tests.factories import make_jwt_private_keys

RAIZ = Path(__file__).resolve().parents[2]
PASTA_AWS = RAIZ / "docker" / "aws"
LAB = PASTA_AWS / "lab.sh"
BASH = shutil.which("bash") or "/bin/bash"
DOCKER = shutil.which("docker")

CONTA = "123456789012"
CHAVE_AWS_S3 = f"arn:aws:kms:us-east-1:{CONTA}:key/0000aaaa-1111-2222-3333-444455556666"
# Credenciais falsas que nunca podem aparecer na saída do script.
CHAVE_DO_PAPEL = "ASIAFALSOPAPEL000001"
SEGREDO_DO_PAPEL = "segredo-falso-do-papel-nunca-na-saida"
TOKEN_DO_PAPEL = "token-falso-do-papel-nunca-na-saida"  # noqa: S105 - valor falso de teste
CHAVE_DE_QUEM_RODA = "ASIAFALSOQUEMRODA001"
COMMIT = "abcdef0123456789abcdef0123456789abcdef01"
IP_ELASTICO = "203.0.113.10"
HOST = "203-0-113-10.sslip.io"
IP_DA_EQUIPE = "198.51.100.7/32"
BUCKET_EXISTENTE = "sgs-lab-relatorios-0a0b0c0d0e0f"

_AWS_FALSO = r'''#!/usr/bin/env python3
"""`aws` falso para os testes do lab.sh: responde e anota cada chamada em $AWS_FALSO_LOG.

$AWS_FALSO_EXISTE lista o que já existe na conta (instancia_running, instancia_stopped, grupo,
bucket, ip). Depois de um delete-object(s), as listagens de versões voltam vazias."""
import base64, hashlib, json, os, sys

args = sys.argv[1:]
globais = {}
while args and args[0] in ("--region", "--output"):
    globais[args[0]] = args[1]
    args = args[2:]
servico, operacao, resto = args[0], args[1], args[2:]
opcoes = {}
chave = None
for parte in resto:
    if chave is None and not parte.startswith("--"):
        opcoes.setdefault("_posicionais", []).append(parte)
    elif parte.startswith("--"):
        chave = parte
        opcoes[chave] = True
    elif opcoes.get(chave) is True:
        opcoes[chave] = parte
    elif isinstance(opcoes.get(chave), list):
        opcoes[chave].append(parte)
    else:
        opcoes[chave] = [opcoes[chave], parte]
registro = {
    "op": f"{servico} {operacao}",
    "opcoes": opcoes,
    "regiao": globais.get("--region"),
    "chave": os.environ.get("AWS_ACCESS_KEY_ID"),
    "token": os.environ.get("AWS_SESSION_TOKEN"),
}
if str(opcoes.get("--user-data", "")).startswith("file://"):
    registro["user_data"] = open(opcoes["--user-data"][len("file://"):], encoding="utf-8").read()
with open(os.environ["AWS_FALSO_LOG"], "a") as log:
    log.write(json.dumps(registro) + "\n")
cenario = os.environ.get("AWS_FALSO_CENARIO", "ok")
conta = os.environ["AWS_FALSO_CONTA"]
existe = set(filter(None, os.environ.get("AWS_FALSO_EXISTE", "").split(",")))
apagados = os.environ["AWS_FALSO_LOG"] + ".apagados"
ip, host, bucket = "203.0.113.10", "203-0-113-10.sslip.io", "sgs-lab-relatorios-0a0b0c0d0e0f"


def erro(codigo, operacao_aws, mensagem):
    sys.stderr.write(
        f"\nAn error occurred ({codigo}) when calling the {operacao_aws} operation: {mensagem}\n"
    )
    sys.exit(254)


def sai(dados=None):
    if dados is not None:
        print(json.dumps(dados))
    sys.exit(0)


op = (servico, operacao)
if op == ("sts", "get-caller-identity"):
    if cenario == "sem_credenciais":
        sys.stderr.write("\nUnable to locate credentials.\n")
        sys.exit(253)
    sai({"UserId": "AROAFALSO:user1", "Account": conta,
         "Arn": f"arn:aws:sts::{conta}:assumed-role/voclabs/user1=Fulano"})
if op == ("sts", "assume-role"):
    if cenario == "assume_negado":
        erro("AccessDenied", "AssumeRole",
             f"User: arn:aws:sts::{conta}:assumed-role/voclabs/user1 is not authorized to perform: "
             f"sts:AssumeRole on resource: {opcoes['--role-arn']}")
    sai({"Credentials": {
        "AccessKeyId": os.environ["AWS_FALSO_CHAVE_PAPEL"],
        "SecretAccessKey": os.environ["AWS_FALSO_SEGREDO_PAPEL"],
        "SessionToken": os.environ["AWS_FALSO_TOKEN_PAPEL"],
        "Expiration": "2026-11-26T20:00:00+00:00"},
        "AssumedRoleUser": {"AssumedRoleId": "AROAFALSO:sgs-sondagem",
                            "Arn": f"arn:aws:sts::{conta}:assumed-role/LabRole/sgs-sondagem"}})
if op == ("kms", "describe-key"):
    sai({"KeyMetadata": {"Arn": os.environ["AWS_FALSO_CHAVE_KMS"], "KeyManager": "AWS"}})
if op == ("ssm", "get-parameter"):
    sai({"Parameter": {"Value": "ami-0falso"}})
if op == ("s3api", "create-bucket"):
    sai({"Location": "/" + opcoes["--bucket"]})
if op == ("s3api", "list-buckets"):
    sai({"Buckets": [{"Name": bucket}] if "bucket" in existe else []})
if op in (("s3api", "delete-object"), ("s3api", "delete-objects")):
    open(apagados, "w").close()
    sai({"Deleted": []} if operacao == "delete-objects" else None)
if op == ("s3api", "list-object-versions"):
    if os.path.exists(apagados):
        sai({})
    sai({"Versions": [{"Key": "reports/sondagem.txt", "VersionId": "v1"}],
         "DeleteMarkers": [{"Key": "reports/velho.csv", "VersionId": "m1"}]})
if op == ("s3api", "put-object"):
    if cenario == "put_negado":
        erro("AccessDenied", "PutObject", "Access Denied")
    corpo = open(opcoes["--body"], "rb").read()
    soma = base64.b64encode(hashlib.sha256(corpo).digest()).decode()
    chave = os.environ["AWS_FALSO_CHAVE_KMS"]
    if cenario == "chave_errada":
        chave = chave.replace("0000aaaa", "9999ffff")
    sai({"ETag": "\"x\"", "ChecksumSHA256": soma, "ServerSideEncryption": "aws:kms",
         "SSEKMSKeyId": chave, "VersionId": "v1"})
if servico == "s3api" and (operacao.startswith("put-bucket") or operacao in (
        "put-public-access-block", "delete-bucket")):
    sai()
if op == ("ec2", "describe-instances"):
    estados = [e.split("_", 1)[1] for e in existe if e.startswith("instancia_")]
    instancias = [{"InstanceId": "i-0falso", "InstanceType": "t3.small",
                   "State": {"Name": estado}} for estado in estados]
    sai({"Reservations": [{"Instances": instancias}] if instancias else []})
if op == ("ec2", "describe-addresses"):
    enderecos = [{"AllocationId": "eipalloc-0falso", "PublicIp": ip}] if "ip" in existe else []
    sai({"Addresses": enderecos})
if op == ("ec2", "allocate-address"):
    sai({"AllocationId": "eipalloc-0falso", "PublicIp": ip})
if op == ("ec2", "describe-security-groups"):
    grupos = [{"GroupId": "sg-0falso", "IpPermissions": [
        {"IpProtocol": "tcp", "FromPort": 443, "ToPort": 443,
         "IpRanges": [{"CidrIp": "192.0.2.99/32"}]},
        {"IpProtocol": "tcp", "FromPort": 80, "ToPort": 80,
         "IpRanges": [{"CidrIp": "0.0.0.0/0"}]}]}] if "grupo" in existe else []
    sai({"SecurityGroups": grupos})
if op == ("ec2", "describe-vpcs"):
    sai({"Vpcs": [{"VpcId": "vpc-0falso"}]})
if op == ("ec2", "create-security-group"):
    sai({"GroupId": "sg-0falso"})
if op == ("ec2", "describe-managed-prefix-lists"):
    sai({"PrefixLists": [{"PrefixListId": "pl-0falso"}]})
if op == ("ec2", "run-instances"):
    sai({"Instances": [{"InstanceId": "i-0falso"}]})
if op == ("ec2", "associate-address"):
    sai({"AssociationId": "eipassoc-0falso"})
if op == ("ec2", "get-console-output"):
    sai({"Output": "[   9.1] cloud-init[1]: sgs-lab: sondar: OK     identidade: "
                   f"arn:aws:sts::{conta}:assumed-role/LabRole/<SESSAO>\n"
                   f"[  12.0] cloud-init[1]: sgs-lab: pronto: https://{host}/\n"
                   "[  12.1] outra linha qualquer\n"})
if servico == "ec2" and operacao in (
        "wait", "authorize-security-group-ingress", "revoke-security-group-ingress",
        "stop-instances", "start-instances", "terminate-instances", "release-address",
        "delete-security-group"):
    sai({} if operacao.endswith("instances") else None)
sys.stderr.write(f"aws falso: operação não prevista: {servico} {operacao}\n")
sys.exit(2)
'''

_GIT_FALSO = r"""#!/usr/bin/env bash
# `git` falso: HEAD fixo; o commit está num ramo remoto, menos no cenário fora_do_remoto.
[[ "$1" == "-C" ]] && shift 2
case "$1 $2" in
"rev-parse HEAD") echo "$GIT_FALSO_COMMIT" ;;
"branch -r") [[ "${GIT_FALSO_CENARIO:-}" == "fora_do_remoto" ]] || echo "  origin/feat/004-005" ;;
*) echo "git falso: comando não previsto: $*" >&2; exit 2 ;;
esac
"""


def _roda_lab(
    tmp_path: Path,
    *argumentos: str,
    cenario: str = "ok",
    existe: tuple[str, ...] = (),
    git: str = "ok",
    ambiente_extra: dict[str, str] | None = None,
) -> tuple[subprocess.CompletedProcess[str], list[dict[str, object]]]:
    bin_falso = tmp_path / "bin"
    bin_falso.mkdir(exist_ok=True)
    for nome, conteudo in (("aws", _AWS_FALSO), ("git", _GIT_FALSO)):
        programa = bin_falso / nome
        programa.write_text(conteudo, encoding="utf-8")
        programa.chmod(0o755)
    log = tmp_path / "chamadas.jsonl"
    log.unlink(missing_ok=True)
    Path(f"{log}.apagados").unlink(missing_ok=True)
    ambiente = {
        "PATH": f"{bin_falso}{os.pathsep}{os.environ['PATH']}",
        "HOME": str(tmp_path),
        "TMPDIR": str(tmp_path),
        "AWS_ACCESS_KEY_ID": CHAVE_DE_QUEM_RODA,
        "AWS_SECRET_ACCESS_KEY": "segredo-falso-de-quem-roda",
        "AWS_FALSO_LOG": str(log),
        "AWS_FALSO_CENARIO": cenario,
        "AWS_FALSO_EXISTE": ",".join(existe),
        "AWS_FALSO_CONTA": CONTA,
        "AWS_FALSO_CHAVE_KMS": CHAVE_AWS_S3,
        "AWS_FALSO_CHAVE_PAPEL": CHAVE_DO_PAPEL,
        "AWS_FALSO_SEGREDO_PAPEL": SEGREDO_DO_PAPEL,
        "AWS_FALSO_TOKEN_PAPEL": TOKEN_DO_PAPEL,
        "GIT_FALSO_COMMIT": COMMIT,
        "GIT_FALSO_CENARIO": git,
        # Sem consulta ao checkip nem espera entre tentativas.
        "SGS_LAB_IPS": IP_DA_EQUIPE,
        "SGS_LAB_ESPERA": "0",
    } | (ambiente_extra or {})
    resultado = subprocess.run(  # noqa: S603 - script do próprio repositório
        [BASH, str(LAB), *argumentos],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
        env=ambiente,
        cwd=tmp_path,
    )
    chamadas = (
        [json.loads(linha) for linha in log.read_text(encoding="utf-8").splitlines()]
        if log.exists()
        else []
    )
    return resultado, chamadas


def _saida(resultado: subprocess.CompletedProcess[str]) -> str:
    return resultado.stdout + resultado.stderr


def _nada_sensivel(saida: str) -> None:
    # O nome da sessão do Learner Lab traz o e-mail de quem roda (aqui, "Fulano").
    for segredo in (SEGREDO_DO_PAPEL, TOKEN_DO_PAPEL, CHAVE_DO_PAPEL, CONTA, "Fulano", "user1"):
        assert segredo not in saida


def _ops(chamadas: list[dict[str, object]]) -> list[object]:
    return [c["op"] for c in chamadas]


def _chamada(chamadas: list[dict[str, object]], op: str) -> dict[str, object]:
    return next(c for c in chamadas if c["op"] == op)


def _opcoes(chamada: dict[str, object]) -> dict[str, object]:
    opcoes = chamada["opcoes"]
    assert isinstance(opcoes, dict)
    return opcoes


def _json(chamada: dict[str, object], opcao: str) -> object:
    valor = _opcoes(chamada)[opcao]
    assert isinstance(valor, str)
    return json.loads(valor)


# --- sondar ---------------------------------------------------------------------------------------


def test_sondar_com_tudo_permitido_indica_o_caminho_do_assume_role(tmp_path: Path) -> None:
    resultado, chamadas = _roda_lab(tmp_path, "sondar")

    saida = _saida(resultado)
    assert resultado.returncode == 0, saida
    assert "caminho: AssumeRole" in saida
    _nada_sensivel(saida)

    assume = next(c for c in chamadas if c["op"] == "sts assume-role")
    opcoes = assume["opcoes"]
    assert isinstance(opcoes, dict)
    assert opcoes["--role-arn"] == f"arn:aws:iam::{CONTA}:role/LabRole"
    assert opcoes["--duration-seconds"] == "900"
    assert opcoes["--external-id"]
    assert all(c["regiao"] == "us-east-1" for c in chamadas)

    # O envio usa as credenciais do papel, com aws:kms na chave aws/s3 e checksum SHA-256.
    envio = next(c for c in chamadas if c["op"] == "s3api put-object")
    assert envio["chave"] == CHAVE_DO_PAPEL
    assert envio["token"] == TOKEN_DO_PAPEL
    opcoes_envio = envio["opcoes"]
    assert isinstance(opcoes_envio, dict)
    assert opcoes_envio["--server-side-encryption"] == "aws:kms"
    assert opcoes_envio["--ssekms-key-id"] == CHAVE_AWS_S3
    assert opcoes_envio["--checksum-algorithm"] == "SHA256"


def test_sondar_apaga_o_bucket_temporario_e_etiqueta_o_recurso(tmp_path: Path) -> None:
    _, chamadas = _roda_lab(tmp_path, "sondar")

    criado = next(c for c in chamadas if c["op"] == "s3api create-bucket")
    opcoes = criado["opcoes"]
    assert isinstance(opcoes, dict)
    bucket = opcoes["--bucket"]
    assert isinstance(bucket, str)
    assert bucket.startswith("sgs-lab-sondagem-")
    etiqueta = next(c for c in chamadas if c["op"] == "s3api put-bucket-tagging")
    assert "sgs-lab" in json.dumps(etiqueta["opcoes"])
    apagado = [c for c in chamadas if c["op"] == "s3api delete-bucket"]
    assert len(apagado) == 1
    assert apagado[0]["opcoes"] == {"--bucket": bucket}
    # A limpeza usa as credenciais de quem roda, não as do papel.
    assert apagado[0]["chave"] == CHAVE_DE_QUEM_RODA
    assert _ops(chamadas).index("s3api delete-object") < _ops(chamadas).index("s3api delete-bucket")


def test_sondar_com_assume_role_negado_indica_a_emenda_e_ainda_testa_o_envio(
    tmp_path: Path,
) -> None:
    resultado, chamadas = _roda_lab(tmp_path, "sondar", cenario="assume_negado")

    saida = _saida(resultado)
    assert resultado.returncode == 1
    assert "AccessDenied" in saida
    assert "caminho: emenda" in saida
    _nada_sensivel(saida)
    # Sem papel, o envio sai com as credenciais de quem roda, para separar as duas falhas.
    envio = next(c for c in chamadas if c["op"] == "s3api put-object")
    assert envio["chave"] == CHAVE_DE_QUEM_RODA
    assert "s3api delete-bucket" in _ops(chamadas)


def test_sondar_recusa_chave_kms_diferente_da_aws_s3(tmp_path: Path) -> None:
    resultado, chamadas = _roda_lab(tmp_path, "sondar", cenario="chave_errada")

    assert resultado.returncode == 1
    assert "SSEKMSKeyId" in _saida(resultado)
    assert "s3api delete-bucket" in _ops(chamadas)


def test_sondar_com_envio_negado_falha_e_limpa(tmp_path: Path) -> None:
    resultado, chamadas = _roda_lab(tmp_path, "sondar", cenario="put_negado")

    assert resultado.returncode == 1
    assert "PutObject" in _saida(resultado)
    assert "s3api delete-bucket" in _ops(chamadas)


def test_sondar_sem_credenciais_para_antes_de_criar_qualquer_recurso(tmp_path: Path) -> None:
    resultado, chamadas = _roda_lab(tmp_path, "sondar", cenario="sem_credenciais")

    assert resultado.returncode == 1
    assert "credenciais" in _saida(resultado)
    assert _ops(chamadas) == ["sts get-caller-identity"]


def test_subcomando_desconhecido_mostra_o_uso(tmp_path: Path) -> None:
    resultado, chamadas = _roda_lab(tmp_path, "nao-existe")

    assert resultado.returncode == 2
    assert "uso:" in _saida(resultado).lower()
    assert chamadas == []


# --- subir ----------------------------------------------------------------------------------------


def test_subir_cria_grupo_com_443_so_da_equipe_e_22_so_do_instance_connect(tmp_path: Path) -> None:
    resultado, chamadas = _roda_lab(tmp_path, "subir")

    assert resultado.returncode == 0, _saida(resultado)
    regras = [
        regra
        for c in chamadas
        if c["op"] == "ec2 authorize-security-group-ingress"
        for regra in _json(c, "--ip-permissions")  # type: ignore[attr-defined]
    ]
    por_porta = {regra["FromPort"]: regra for regra in regras}
    assert set(por_porta) == {80, 22, 443}
    assert [r["CidrIp"] for r in por_porta[443]["IpRanges"]] == [IP_DA_EQUIPE]
    assert [r["CidrIp"] for r in por_porta[80]["IpRanges"]] == ["0.0.0.0/0"]
    assert "IpRanges" not in por_porta[22]
    assert por_porta[22]["PrefixListIds"] == [
        {"PrefixListId": "pl-0falso", "Description": "EC2 Instance Connect"}
    ]
    lista = _opcoes(_chamada(chamadas, "ec2 describe-managed-prefix-lists"))["--filters"]
    assert lista == "Name=prefix-list-name,Values=com.amazonaws.us-east-1.ec2-instance-connect"


def test_subir_cria_bucket_privado_versionado_com_kms_tls_e_guarda(tmp_path: Path) -> None:
    resultado, chamadas = _roda_lab(tmp_path, "subir")

    assert resultado.returncode == 0, _saida(resultado)
    bucket = _opcoes(_chamada(chamadas, "s3api create-bucket"))["--bucket"]
    assert isinstance(bucket, str)
    assert re.fullmatch(r"sgs-lab-relatorios-[0-9a-f]{12}", bucket)
    bloqueio = _opcoes(_chamada(chamadas, "s3api put-public-access-block"))
    assert bloqueio["--public-access-block-configuration"] == (
        "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"
    )
    versao = _opcoes(_chamada(chamadas, "s3api put-bucket-versioning"))
    assert versao["--versioning-configuration"] == "Status=Enabled"
    cifra = _json(
        _chamada(chamadas, "s3api put-bucket-encryption"), "--server-side-encryption-configuration"
    )
    assert cifra == {
        "Rules": [
            {
                "ApplyServerSideEncryptionByDefault": {
                    "SSEAlgorithm": "aws:kms",
                    "KMSMasterKeyID": CHAVE_AWS_S3,
                }
            }
        ]
    }
    politica = _json(_chamada(chamadas, "s3api put-bucket-policy"), "--policy")
    assert isinstance(politica, dict)
    negacoes = {d["Sid"]: d for d in politica["Statement"]}
    assert negacoes["NegaSemTLS"]["Condition"] == {"Bool": {"aws:SecureTransport": "false"}}
    assert negacoes["NegaSemTLS"]["Resource"] == [
        f"arn:aws:s3:::{bucket}",
        f"arn:aws:s3:::{bucket}/*",
    ]
    assert negacoes["NegaPutSemKmsValorErrado"]["Condition"] == {
        "StringNotEquals": {"s3:x-amz-server-side-encryption": "aws:kms"}
    }
    assert negacoes["NegaPutSemKmsCabecalhoAusente"]["Condition"] == {
        "Null": {"s3:x-amz-server-side-encryption": "true"}
    }
    assert all(d["Effect"] == "Deny" for d in politica["Statement"])
    ciclo = _json(
        _chamada(chamadas, "s3api put-bucket-lifecycle-configuration"), "--lifecycle-configuration"
    )
    assert isinstance(ciclo, dict)
    regras = {r["ID"]: r for r in ciclo["Rules"]}
    guarda = regras["sgs-relatorios-90-dias"]
    assert guarda["Filter"] == {"Prefix": "reports/"}
    assert guarda["Expiration"] == {"Days": 90}
    assert guarda["NoncurrentVersionExpiration"] == {"NoncurrentDays": 1}
    assert regras["sgs-marcadores-orfaos"]["Expiration"] == {"ExpiredObjectDeleteMarker": True}
    assert "sgs-lab" in str(_opcoes(_chamada(chamadas, "s3api put-bucket-tagging"))["--tagging"])


def test_subir_lanca_instancia_pequena_com_perfil_do_lab_e_imdsv2(tmp_path: Path) -> None:
    resultado, chamadas = _roda_lab(tmp_path, "subir")

    saida = _saida(resultado)
    assert resultado.returncode == 0, saida
    _nada_sensivel(saida)
    instancia = _opcoes(_chamada(chamadas, "ec2 run-instances"))
    assert instancia["--image-id"] == "ami-0falso"
    assert instancia["--instance-type"] == "t3.small"
    assert instancia["--iam-instance-profile"] == "Name=LabInstanceProfile"
    assert instancia["--security-group-ids"] == "sg-0falso"
    # IMDSv2 com salto 2: a API, dentro de um contêiner, chega ao perfil da instância.
    assert (
        instancia["--metadata-options"]
        == "HttpTokens=required,HttpPutResponseHopLimit=2,HttpEndpoint=enabled"
    )
    # Créditos unlimited: em standard, o t3 novo começa sem créditos, fica preso em 20% de CPU e
    # o Keycloak não termina a 1ª subida (1ª subida real, 26/11/2026; decisão do Rafael).
    assert instancia["--credit-specification"] == "CpuCredits=unlimited"
    (disco,) = json.loads(str(instancia["--block-device-mappings"]))
    assert disco["Ebs"] == {
        "VolumeSize": 20,
        "VolumeType": "gp3",
        "Encrypted": True,
        "DeleteOnTermination": True,
    }
    assert "Key=Projeto,Value=sgs-lab" in str(instancia["--tag-specifications"])
    # O IP elástico é associado à instância criada, e os endereços saem pelo nome sslip.io.
    associacao = _opcoes(_chamada(chamadas, "ec2 associate-address"))
    assert associacao == {"--instance-id": "i-0falso", "--allocation-id": "eipalloc-0falso"}
    assert f"https://{HOST}/" in saida
    assert f"https://keycloak.{HOST}/" in saida
    assert _ops(chamadas).index("ec2 wait") < _ops(chamadas).index("ec2 associate-address")


def test_subir_envia_user_data_com_todos_os_marcadores_trocados(tmp_path: Path) -> None:
    _, chamadas = _roda_lab(tmp_path, "subir")

    user_data = _chamada(chamadas, "ec2 run-instances")["user_data"]
    assert isinstance(user_data, str)
    assert "__SGS_LAB_" not in user_data
    bucket = _opcoes(_chamada(chamadas, "s3api create-bucket"))["--bucket"]
    for linha in (
        'REPOSITORIO="https://github.com/rafareloM/sgs-api.git"',
        f'COMMIT="{COMMIT}"',
        'REGIAO="us-east-1"',
        f'BUCKET="{bucket}"',
        f'PAPEL_ARN="arn:aws:iam::{CONTA}:role/LabRole"',
        f'CHAVE_KMS_ARN="{CHAVE_AWS_S3}"',
        f'HOST="{HOST}"',
    ):
        assert linha in user_data
    assert re.search(r'^EXTERNAL_ID="sgs-lab-[0-9a-f]{12}"$', user_data, re.MULTILINE)


def test_subir_recusa_commit_que_nao_esta_no_github(tmp_path: Path) -> None:
    resultado, chamadas = _roda_lab(tmp_path, "subir", git="fora_do_remoto")

    assert resultado.returncode == 1
    assert "push" in _saida(resultado)
    assert all(str(op).split()[1].startswith(("get-", "describe-")) for op in _ops(chamadas))


def test_subir_recusa_quando_ja_existe_instancia(tmp_path: Path) -> None:
    resultado, chamadas = _roda_lab(tmp_path, "subir", existe=("instancia_stopped",))

    assert resultado.returncode == 1
    assert "i-0falso (stopped)" in _saida(resultado)
    assert "ec2 run-instances" not in _ops(chamadas)


@pytest.mark.parametrize("faixa", ["0.0.0.0/0", "10.0.0.0/8", "198.51.100.7", "não-é-ip/32"])
def test_subir_recusa_abrir_a_443_para_faixa_larga_ou_invalida(tmp_path: Path, faixa: str) -> None:
    resultado, chamadas = _roda_lab(
        tmp_path, "subir", ambiente_extra={"SGS_LAB_IPS": f"{IP_DA_EQUIPE},{faixa}"}
    )

    assert resultado.returncode == 1
    assert "faixa recusada" in _saida(resultado)
    assert not any(
        str(op).split()[1].startswith(("create-", "allocate-", "run-", "authorize-"))
        for op in _ops(chamadas)
    )


def test_subir_reaproveita_grupo_bucket_e_ip_que_ja_existem(tmp_path: Path) -> None:
    resultado, chamadas = _roda_lab(tmp_path, "subir", existe=("grupo", "bucket", "ip"))

    assert resultado.returncode == 0, _saida(resultado)
    ops = _ops(chamadas)
    for criacao in ("ec2 create-security-group", "s3api create-bucket", "ec2 allocate-address"):
        assert criacao not in ops
    # A 443 antiga sai; a nova lista entra.
    revogadas = _json(_chamada(chamadas, "ec2 revoke-security-group-ingress"), "--ip-permissions")
    assert revogadas == [
        {
            "IpProtocol": "tcp",
            "FromPort": 443,
            "ToPort": 443,
            "IpRanges": [{"CidrIp": "192.0.2.99/32"}],
        }
    ]
    assert f'BUCKET="{BUCKET_EXISTENTE}"' in str(
        _chamada(chamadas, "ec2 run-instances")["user_data"]
    )


# --- estado, liberar-ip, parar, ligar -------------------------------------------------------------


def test_estado_mostra_enderecos_lista_da_443_e_progresso_mascarado(tmp_path: Path) -> None:
    resultado, _ = _roda_lab(
        tmp_path, "estado", existe=("instancia_running", "grupo", "bucket", "ip")
    )

    saida = _saida(resultado)
    assert resultado.returncode == 0, saida
    _nada_sensivel(saida)
    assert "instância i-0falso, t3.small: running" in saida
    assert f"https://{HOST}/" in saida
    assert "443 liberada para: 192.0.2.99/32" in saida
    assert BUCKET_EXISTENTE in saida
    assert "sgs-lab: pronto:" in saida
    assert "outra linha qualquer" not in saida


def test_liberar_ip_troca_a_lista_da_443(tmp_path: Path) -> None:
    resultado, chamadas = _roda_lab(
        tmp_path,
        "liberar-ip",
        existe=("grupo",),
        ambiente_extra={"SGS_LAB_IPS": "198.51.100.7/32,203.0.113.0/24"},
    )

    assert resultado.returncode == 0, _saida(resultado)
    regras = _json(_chamada(chamadas, "ec2 authorize-security-group-ingress"), "--ip-permissions")
    assert isinstance(regras, list)
    (novas,) = regras
    assert [r["CidrIp"] for r in novas["IpRanges"]] == ["198.51.100.7/32", "203.0.113.0/24"]
    assert "ec2 revoke-security-group-ingress" in _ops(chamadas)


def test_parar_e_ligar_mexem_so_na_instancia_do_lab(tmp_path: Path) -> None:
    parada, chamadas_parar = _roda_lab(tmp_path, "parar", existe=("instancia_running",))
    ligada, chamadas_ligar = _roda_lab(tmp_path, "ligar", existe=("instancia_stopped", "ip"))

    assert parada.returncode == 0, _saida(parada)
    assert _opcoes(_chamada(chamadas_parar, "ec2 stop-instances")) == {"--instance-ids": "i-0falso"}
    assert ligada.returncode == 0, _saida(ligada)
    assert _opcoes(_chamada(chamadas_ligar, "ec2 start-instances")) == {
        "--instance-ids": "i-0falso"
    }
    assert f"https://{HOST}/" in _saida(ligada)
    filtros = _opcoes(_chamada(chamadas_parar, "ec2 describe-instances"))["--filters"]
    assert "Name=tag:Projeto,Values=sgs-lab" in filtros  # type: ignore[operator]


def test_parar_sem_instancia_falha(tmp_path: Path) -> None:
    resultado, chamadas = _roda_lab(tmp_path, "parar")

    assert resultado.returncode == 1
    assert "ec2 stop-instances" not in _ops(chamadas)


# --- destruir -------------------------------------------------------------------------------------


def test_destruir_sem_confirmacao_nao_chama_a_aws(tmp_path: Path) -> None:
    resultado, chamadas = _roda_lab(
        tmp_path, "destruir", existe=("instancia_running", "grupo", "bucket", "ip")
    )

    assert resultado.returncode == 1
    assert "--confirmo" in _saida(resultado)
    assert chamadas == []


def test_destruir_apaga_tudo_na_ordem_certa(tmp_path: Path) -> None:
    resultado, chamadas = _roda_lab(
        tmp_path, "destruir", "--confirmo", existe=("instancia_running", "grupo", "bucket", "ip")
    )

    assert resultado.returncode == 0, _saida(resultado)
    ops = _ops(chamadas)
    ordem = [
        "ec2 terminate-instances",
        "ec2 wait",
        "ec2 release-address",
        "s3api delete-objects",
        "s3api delete-bucket",
        "ec2 delete-security-group",
    ]
    assert [op for op in ops if op in ordem] == ordem
    # Todas as versões e marcadores saem antes de apagar o bucket.
    lote = _json(_chamada(chamadas, "s3api delete-objects"), "--delete")
    assert lote == {
        "Objects": [
            {"Key": "reports/sondagem.txt", "VersionId": "v1"},
            {"Key": "reports/velho.csv", "VersionId": "m1"},
        ],
        "Quiet": True,
    }
    assert _opcoes(_chamada(chamadas, "s3api delete-bucket")) == {"--bucket": BUCKET_EXISTENTE}


# --- evidencia ------------------------------------------------------------------------------------


def _funcao_do_lab(*comando: str) -> str:
    """Carrega o lab.sh com `source` (sem rodar o principal) e chama uma função dele."""
    script = f'source "{LAB}"; ' + " ".join(f"'{parte}'" for parte in comando)
    resultado = subprocess.run(  # noqa: S603 - script do próprio repositório
        [BASH, "-c", script], capture_output=True, text=True, check=True, timeout=30
    )
    return resultado.stdout.strip()


@pytest.mark.parametrize(("instante", "codigo"), [("59", "287082"), ("1111111109", "081804")])
def test_totp_segue_os_vetores_da_rfc_6238(instante: str, codigo: str) -> None:
    # Segredo ASCII "12345678901234567890" da RFC 6238, apêndice B (SHA-1), em base32.
    uri = "otpauth://totp/sgs:admin?secret=GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ&issuer=sgs"
    assert _funcao_do_lab("totp", uri, instante) == codigo


def test_sanitizar_evidencia_tira_conta_ip_e_assinatura() -> None:
    texto = (
        f"conta {CONTA}; ip {IP_ELASTICO}; host https://{HOST}/; "
        "url https://b.s3.amazonaws.com/k?X-Amz-Signature=abc123&X-Amz-Security-Token=tok&a=1"
    )
    saida = _funcao_do_lab("eval", f"printf '%s' \"{texto}\" | sanitizar_evidencia {IP_ELASTICO}")

    assert CONTA not in saida
    assert IP_ELASTICO not in saida
    assert HOST not in saida
    assert "abc123" not in saida
    assert "tok" not in saida
    assert "<ID_DA_CONTA>" in saida
    assert "https://<IP_DO_LAB>.sslip.io/" in saida


def test_evidencia_sem_o_laboratorio_no_ar_falha_sem_mexer_em_nada(tmp_path: Path) -> None:
    resultado, chamadas = _roda_lab(tmp_path, "evidencia")

    assert resultado.returncode == 1
    assert "não está no ar" in _saida(resultado)
    assert all(
        str(op).split()[1].startswith(("get-", "describe-", "list-")) for op in _ops(chamadas)
    )


def test_evidencia_sem_a_senha_do_admin_explica_onde_buscar(tmp_path: Path) -> None:
    resultado, chamadas = _roda_lab(
        tmp_path,
        "evidencia",
        existe=("instancia_running", "bucket", "ip"),
        ambiente_extra={"SGS_LAB_CONFIG": str(tmp_path / "config")},
    )

    saida = _saida(resultado)
    assert resultado.returncode == 1
    assert "senha do administrador" in saida
    assert "/opt/sgs/credenciais-do-lab" in saida
    assert all(
        str(op).split()[1].startswith(("get-", "describe-", "list-")) for op in _ops(chamadas)
    )
    assert "evidência gravada" not in saida


# --- sobreposição do compose e Caddyfile ----------------------------------------------------------

AMBIENTE_DO_LAB = {
    "SGS_BORDA_SUBNET": "10.231.98.0/28",
    "SGS_BORDA_PROXY_IP": "10.231.98.14",
    "SGS_PUBLIC_URL": f"https://{HOST}",
    "SGS_PUBLIC_KEYCLOAK_URL": f"https://keycloak.{HOST}",
    "SGS_CORS_ORIGINS": f"https://{HOST}",
    "SGS_LAB_HOST": HOST,
    "SGS_LAB_BUCKET": BUCKET_EXISTENTE,
    "SGS_LAB_PAPEL_ARN": f"arn:aws:iam::{CONTA}:role/LabRole",
    "SGS_LAB_EXTERNAL_ID": "sgs-lab-0a0b0c0d0e0f",
    "SGS_LAB_CHAVE_KMS_ARN": CHAVE_AWS_S3,
}


def _compose_do_lab() -> dict[str, object]:
    if DOCKER is None:
        pytest.skip("sem Docker: a sobreposição do compose não foi resolvida")
    limpo = {k: v for k, v in os.environ.items() if not k.startswith("SGS_")}
    resolvido = subprocess.run(  # noqa: S603 - comando fixo, sem entrada externa
        [
            DOCKER,
            "compose",
            "-f",
            str(RAIZ / "docker" / "compose.yml"),
            "-f",
            str(PASTA_AWS / "compose.aws.yml"),
            "-p",
            "sgs-api-laboratorio-aws",
            "config",
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
        cwd=RAIZ / "tests",
        env=limpo | {"COMPOSE_DISABLE_ENV_FILE": "true"} | AMBIENTE_DO_LAB,
    )
    assert resolvido.returncode == 0, resolvido.stderr
    configuracao = json.loads(resolvido.stdout)
    assert isinstance(configuracao, dict)
    return configuracao


def test_compose_do_lab_sobe_sem_seaweedfs() -> None:
    servicos = _compose_do_lab()["services"]
    assert isinstance(servicos, dict)
    assert {"s3", "s3-init"}.isdisjoint(servicos)
    assert {"api", "db", "proxy", "keycloak", "ldap"} <= set(servicos)
    proxy = servicos["proxy"]
    caddyfile = next(v for v in proxy["volumes"] if v["target"] == "/etc/caddy/Caddyfile")
    assert caddyfile["source"] == str(PASTA_AWS / "Caddyfile")
    assert proxy["environment"]["SGS_LAB_HOST"] == HOST
    assert "-Xmx512m" in servicos["keycloak"]["environment"]["JAVA_OPTS_KC_HEAP"]
    # A primeira subida do Keycloak num t3.small passa de 3 minutos (1ª subida real, 26/11/2026).
    assert servicos["keycloak"]["healthcheck"]["start_period"] == "10m0s"
    assert servicos["keycloak"]["healthcheck"]["test"]  # o teste do compose local continua


def test_api_do_lab_usa_assume_role_e_kms_sem_chave_fixa(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R2.1 a R2.3 numa conta real: papel por operação, aws:kms, nada de chave fixa (R2.2)."""
    servicos = _compose_do_lab()["services"]
    assert isinstance(servicos, dict)
    ambiente = {k: v for k, v in servicos["api"]["environment"].items() if v is not None}
    conteudos = {
        "JWT_PRIVATE_KEYS_FILE": make_jwt_private_keys("lab"),
        "CRYPTO_KEYS_FILE": json.dumps(novas_chaves()),
        "REPORT_SIGNING_KEYS_FILE": make_jwt_private_keys("rel-lab"),
    }
    for chave, valor in list(ambiente.items()):
        if chave.endswith(("_FILE", "_CERT")) and valor.startswith("/"):
            arquivo = tmp_path / chave.lower()
            arquivo.write_text(conteudos.get(chave, ""), encoding="utf-8")
            ambiente[chave] = str(arquivo)
    for chave in list(os.environ):
        monkeypatch.delenv(chave)
    for chave, valor in ambiente.items():
        monkeypatch.setenv(chave, valor)

    config = load_settings()

    assert config.s3_bucket == BUCKET_EXISTENTE
    assert config.s3_assume_role_arn == f"arn:aws:iam::{CONTA}:role/LabRole"
    assert config.s3_external_id
    assert config.s3_sse == "aws:kms"
    assert config.s3_kms_key_id == CHAVE_AWS_S3
    assert config.s3_endpoint_url is None
    assert config.s3_public_endpoint_url is None
    assert config.s3_ca_file is None
    assert config.s3_access_key_id is None
    assert config.s3_secret_access_key is None
    assert config.oidc_issuer == f"https://keycloak.{HOST}/realms/sgs"


def test_caddyfile_do_lab_usa_lets_encrypt_e_nao_expoe_o_s3() -> None:
    texto = (PASTA_AWS / "Caddyfile").read_text(encoding="utf-8")
    sem_comentarios = "\n".join(
        linha for linha in texto.splitlines() if not linha.lstrip().startswith("#")
    )
    assert "tls internal" not in sem_comentarios
    assert "{$SGS_LAB_HOST} {" in sem_comentarios
    assert "keycloak.{$SGS_LAB_HOST} {" in sem_comentarios
    assert "s3:8333" not in sem_comentarios
    # O bloco do sistema leva a mesma CSP do Caddyfile local.
    local = (RAIZ / "docker" / "caddy" / "Caddyfile").read_text(encoding="utf-8")
    (csp,) = re.findall(r'Content-Security-Policy "[^"]+"', local)
    assert csp in sem_comentarios


# --- conferências estáticas de docker/aws/ --------------------------------------------------------

CONTA_AWS = re.compile(r"(?<![0-9])[0-9]{12}(?![0-9])")
CHAVE_DE_ACESSO = re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b")


def _arquivos_aws() -> list[Path]:
    return sorted(p for p in PASTA_AWS.rglob("*") if p.is_file())


def test_docker_aws_nao_traz_id_de_conta_nem_chave_de_acesso() -> None:
    arquivos = _arquivos_aws()
    assert arquivos
    for arquivo in arquivos:
        texto = arquivo.read_text(encoding="utf-8")
        assert not CONTA_AWS.search(texto), f"{arquivo.name}: parece id de conta AWS"
        assert not CHAVE_DE_ACESSO.search(texto), f"{arquivo.name}: parece chave de acesso"


def test_scripts_de_docker_aws_passam_no_shellcheck() -> None:
    shellcheck = shutil.which("shellcheck")
    if shellcheck is None:
        pytest.fail(
            "shellcheck não instalado: `uv tool install shellcheck-py` (spec 005, T13); "
            "este teste não pula para não esconder o script sem conferência"
        )
    scripts = sorted(PASTA_AWS.glob("*.sh"))
    assert scripts
    resultado = subprocess.run(  # noqa: S603 - ferramenta fixa sobre arquivos do repositório
        [shellcheck, "--severity=style", *map(str, scripts)],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert resultado.returncode == 0, resultado.stdout + resultado.stderr
