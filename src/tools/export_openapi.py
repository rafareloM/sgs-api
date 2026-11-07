"""Exporta o contrato OpenAPI para `contracts/openapi.yaml` (`make openapi`).

A saída é JSON indentado, que também é YAML 1.2 válido; assim o projeto não depende do PyYAML.
Os bytes são escritos em UTF-8 com LF, iguais em qualquer sistema operacional.
"""

import json
import sys

from pydantic import SecretStr

from src.core.config import AppEnv, DatabaseSslMode, Settings
from src.main import create_app
from src.tools.jwt_keys import new_signing_key

# Nenhuma conexão é aberta para gerar o contrato; a URL só precisa ser válida.
_CONTRACT_DATABASE_URL = "postgresql+asyncpg://contrato:contrato@localhost:5432/contrato"


def build_contract() -> str:
    settings = Settings(
        app_env=AppEnv.TEST,
        database_url=SecretStr(_CONTRACT_DATABASE_URL),
        database_ssl_mode=DatabaseSslMode.DISABLE,
        # O contrato não depende da chave: uma descartável, gerada agora, basta. O arquivo de
        # chaves fica vazio de propósito, para um JWT_PRIVATE_KEYS_FILE do ambiente não somar.
        jwt_private_keys=json.dumps([new_signing_key("contrato")]),
        jwt_private_keys_file=(),
    )
    schema = create_app(settings).openapi()
    return json.dumps(schema, indent=2, ensure_ascii=False) + "\n"


def main() -> None:
    sys.stdout.buffer.write(build_contract().encode("utf-8"))


if __name__ == "__main__":
    main()
