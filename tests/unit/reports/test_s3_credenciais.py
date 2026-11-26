"""Os clientes S3 e STS não leem os arquivos compartilhados da AWS (005/T4, P3; R2.2).

O botocore leria `~/.aws/credentials` e `~/.aws/config` antes do papel do contêiner, e nenhuma
variável de ambiente denuncia esses arquivos para a recusa da subida.
"""

from pathlib import Path

import pytest

from src.modules.reports.infrastructure.s3_storage import _novo_cliente

CHAVE_DO_ARQUIVO = "AKIAARQUIVOEXEMPLO00"


def test_cliente_nao_le_credenciais_nem_configuracao_do_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """005/R2.2"""
    aws = tmp_path / ".aws"
    aws.mkdir()
    (aws / "credentials").write_text(
        f"[default]\naws_access_key_id = {CHAVE_DO_ARQUIVO}\naws_secret_access_key = segredo\n",
        encoding="utf-8",
    )
    (aws / "config").write_text(
        "[default]\ncredential_process = /bin/false\nregion = sa-east-1\n", encoding="utf-8"
    )
    for variavel in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        monkeypatch.delenv(variavel, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    # Sem a busca no serviço de metadados da EC2, que não existe aqui.
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")

    cliente = _novo_cliente("sts", region_name="us-east-1")

    credenciais = cliente._request_signer._credentials
    assert credenciais is None or credenciais.access_key != CHAVE_DO_ARQUIVO
