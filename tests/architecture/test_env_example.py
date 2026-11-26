"""O `.env.example` passa pela validação da subida (005/T4 P1 e retro de 26/11/2026).

O arquivo é o modelo do `.env` de quem roda a API fora do compose. Em 25/11/2026 ele trazia
`S3_ENDPOINT_URL=http://`, que a R2.7 recusa, sem nenhuma verificação avisar. Aqui as variáveis
dele passam pelo `load_settings()`, o mesmo da subida. As do compose (`SGS_*`) e os caminhos de
arquivo de dentro do contêiner são trocados por equivalentes locais.
"""

import json
import os
from pathlib import Path

import pytest

from src.core.config import load_settings
from src.tools.crypto_keys import novas_chaves
from tests.factories import make_jwt_private_keys

RAIZ = Path(__file__).resolve().parents[2]
EXEMPLO = RAIZ / ".env.example"


def _variaveis() -> dict[str, str]:
    variaveis = {}
    for linha in EXEMPLO.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, valor = linha.split("=", 1)
        variaveis[chave.strip()] = valor.strip()
    return variaveis


def test_env_example_passa_pela_validacao_da_subida(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """001/R2.1, 005/R2.7: a configuração de exemplo é aceita como está."""
    conteudos = {
        "JWT_PRIVATE_KEYS_FILE": make_jwt_private_keys("exemplo"),
        "CRYPTO_KEYS_FILE": json.dumps(novas_chaves()),
        "REPORT_SIGNING_KEYS_FILE": make_jwt_private_keys("rel-exemplo"),
    }
    for chave in list(os.environ):
        monkeypatch.delenv(chave)
    for chave, valor in _variaveis().items():
        if chave.startswith("SGS_"):
            continue  # do compose, não da API
        if chave.endswith(("_FILE", "_CERT")) and valor.startswith("/"):
            arquivo = tmp_path / chave.lower()
            arquivo.write_text(conteudos.get(chave, ""), encoding="utf-8")
            valor = str(arquivo)
        monkeypatch.setenv(chave, valor)

    settings = load_settings()

    assert settings.exportacao_ligada
    assert settings.s3_endpoint_url is not None
    assert settings.s3_endpoint_url.startswith("https://")
