"""Laboratório na AWS (spec 005, T13): os scripts de `docker/aws/`.

Nada aqui fala com a AWS. O `lab.sh` roda com um `aws` falso no PATH (`_AWS_FALSO`), que responde
como o AWS CLI v2 e anota cada chamada, com as credenciais do ambiente, num arquivo. Assim se
confere o que o script decide, sem conta e sem rede.
"""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
PASTA_AWS = RAIZ / "docker" / "aws"
LAB = PASTA_AWS / "lab.sh"
BASH = shutil.which("bash") or "/bin/bash"

CONTA = "123456789012"
CHAVE_AWS_S3 = f"arn:aws:kms:us-east-1:{CONTA}:key/0000aaaa-1111-2222-3333-444455556666"
# Credenciais falsas que nunca podem aparecer na saída do script.
CHAVE_DO_PAPEL = "ASIAFALSOPAPEL000001"
SEGREDO_DO_PAPEL = "segredo-falso-do-papel-nunca-na-saida"
TOKEN_DO_PAPEL = "token-falso-do-papel-nunca-na-saida"  # noqa: S105 - valor falso de teste
CHAVE_DE_QUEM_RODA = "ASIAFALSOQUEMRODA001"

_AWS_FALSO = r'''#!/usr/bin/env python3
"""`aws` falso para os testes do lab.sh: responde e anota cada chamada em $AWS_FALSO_LOG."""
import base64, hashlib, json, os, sys

args = sys.argv[1:]
globais = {}
while args and args[0] in ("--region", "--output"):
    globais[args[0]] = args[1]
    args = args[2:]
servico, operacao, resto = args[0], args[1], args[2:]
opcoes = {}
i = 0
while i < len(resto):
    if i + 1 < len(resto) and not resto[i + 1].startswith("--"):
        opcoes[resto[i]] = resto[i + 1]
        i += 2
    else:
        opcoes[resto[i]] = True
        i += 1
with open(os.environ["AWS_FALSO_LOG"], "a") as log:
    log.write(json.dumps({
        "op": f"{servico} {operacao}",
        "opcoes": opcoes,
        "regiao": globais.get("--region"),
        "chave": os.environ.get("AWS_ACCESS_KEY_ID"),
        "token": os.environ.get("AWS_SESSION_TOKEN"),
    }) + "\n")
cenario = os.environ.get("AWS_FALSO_CENARIO", "ok")
conta = os.environ["AWS_FALSO_CONTA"]


def erro(codigo, operacao_aws, mensagem):
    sys.stderr.write(
        f"\nAn error occurred ({codigo}) when calling the {operacao_aws} operation: {mensagem}\n"
    )
    sys.exit(254)


def sai(dados):
    print(json.dumps(dados))
    sys.exit(0)


if (servico, operacao) == ("sts", "get-caller-identity"):
    if cenario == "sem_credenciais":
        sys.stderr.write("\nUnable to locate credentials.\n")
        sys.exit(253)
    sai({"UserId": "AROAFALSO:user1", "Account": conta,
         "Arn": f"arn:aws:sts::{conta}:assumed-role/voclabs/user1=Fulano"})
if (servico, operacao) == ("sts", "assume-role"):
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
if (servico, operacao) == ("kms", "describe-key"):
    sai({"KeyMetadata": {"Arn": os.environ["AWS_FALSO_CHAVE_KMS"], "KeyManager": "AWS"}})
if (servico, operacao) == ("s3api", "create-bucket"):
    sai({"Location": "/" + opcoes["--bucket"]})
if (servico, operacao) in (("s3api", "put-bucket-tagging"), ("s3api", "delete-bucket"),
                           ("s3api", "delete-object")):
    sys.exit(0)
if (servico, operacao) == ("s3api", "put-object"):
    if cenario == "put_negado":
        erro("AccessDenied", "PutObject", "Access Denied")
    corpo = open(opcoes["--body"], "rb").read()
    soma = base64.b64encode(hashlib.sha256(corpo).digest()).decode()
    chave = os.environ["AWS_FALSO_CHAVE_KMS"]
    if cenario == "chave_errada":
        chave = chave.replace("0000aaaa", "9999ffff")
    sai({"ETag": "\"x\"", "ChecksumSHA256": soma, "ServerSideEncryption": "aws:kms",
         "SSEKMSKeyId": chave, "VersionId": "v1"})
if (servico, operacao) == ("s3api", "list-object-versions"):
    sai({"Versions": [{"Key": "reports/sondagem.txt", "VersionId": "v1"}]})
sys.stderr.write(f"aws falso: operação não prevista: {servico} {operacao}\n")
sys.exit(2)
'''


def _roda_lab(
    tmp_path: Path, *argumentos: str, cenario: str = "ok"
) -> tuple[subprocess.CompletedProcess[str], list[dict[str, object]]]:
    bin_falso = tmp_path / "bin"
    bin_falso.mkdir(exist_ok=True)
    aws = bin_falso / "aws"
    aws.write_text(_AWS_FALSO, encoding="utf-8")
    aws.chmod(0o755)
    log = tmp_path / "chamadas.jsonl"
    log.unlink(missing_ok=True)
    ambiente = {
        "PATH": f"{bin_falso}{os.pathsep}{os.environ['PATH']}",
        "HOME": str(tmp_path),
        "TMPDIR": str(tmp_path),
        "AWS_ACCESS_KEY_ID": CHAVE_DE_QUEM_RODA,
        "AWS_SECRET_ACCESS_KEY": "segredo-falso-de-quem-roda",
        "AWS_FALSO_LOG": str(log),
        "AWS_FALSO_CENARIO": cenario,
        "AWS_FALSO_CONTA": CONTA,
        "AWS_FALSO_CHAVE_KMS": CHAVE_AWS_S3,
        "AWS_FALSO_CHAVE_PAPEL": CHAVE_DO_PAPEL,
        "AWS_FALSO_SEGREDO_PAPEL": SEGREDO_DO_PAPEL,
        "AWS_FALSO_TOKEN_PAPEL": TOKEN_DO_PAPEL,
    }
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
    for segredo in (SEGREDO_DO_PAPEL, TOKEN_DO_PAPEL, CHAVE_DO_PAPEL, CONTA):
        assert segredo not in saida


def _ops(chamadas: list[dict[str, object]]) -> list[object]:
    return [c["op"] for c in chamadas]


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
