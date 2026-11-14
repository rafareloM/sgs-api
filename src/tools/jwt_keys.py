"""Gera uma chave de assinatura JWT no formato de JWT_PRIVATE_KEYS (spec 002, § Chaves JWT).

    uv run python -m src.tools.jwt_keys --output secrets/jwt-keys.json

Sem `--output`, escreve na saída padrão. Sai uma lista JSON com um objeto `{"kid", "pem"}`:
chave privada EC P-256 (ES256) em PEM, nova a cada execução. Na rotação, ponha a chave nova no
começo da lista (a primeira assina) e mantenha as antigas até os tokens assinados por elas
vencerem. O arquivo é segredo: `secrets/` fica fora do Git.
"""

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

from src.core.config import JWT_KID


def new_signing_key(kid: str) -> dict[str, str]:
    """Chave privada EC P-256 nova, sem senha, no formato de um item de JWT_PRIVATE_KEYS."""
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode()
    return {"kid": kid, "pem": pem}


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m src.tools.jwt_keys",
        description="Gera uma chave de assinatura JWT (ES256) no formato de JWT_PRIVATE_KEYS.",
    )
    parser.add_argument(
        "--kid",
        default=datetime.now(UTC).strftime("%Y-%m-%d"),
        help="identificador da chave no cabeçalho dos tokens e no JWKS (padrão: a data de hoje)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="arquivo a criar, em UTF-8 (o '>' do PowerShell 5.1 gravaria UTF-16)",
    )
    args = parser.parse_args(argv)
    if not JWT_KID.fullmatch(args.kid):
        parser.error("kid inválido; use até 64 letras, dígitos, '.', '-' ou '_'")
    content = json.dumps([new_signing_key(args.kid)]) + "\n"
    if args.output is None:
        sys.stdout.write(content)
    else:
        args.output.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()
