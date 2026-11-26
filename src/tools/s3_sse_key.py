"""Gera o `security.toml` do SeaweedFS de laboratório, com a chave da SSE-S3 (spec 005, T8).

    uv run python -m src.tools.s3_sse_key --output secrets/s3-security.toml

Sem `--output`, escreve na saída padrão. Sai a seção `[s3.sse]` com `key`, um texto secreto do
qual o SeaweedFS deriva a chave AES de 256 bits (HKDF-SHA256). Sem ela, o SeaweedFS recusa todo
envio com `ServerSideEncryption=AES256` (500), e nenhum relatório é gravado (005/T10). O compose
monta o arquivo como segredo em `/etc/seaweedfs/security.toml`, nunca como variável de ambiente
(decisão do Rafael, 26/11/2026). Trocar a chave torna ilegíveis os objetos já gravados: gere uma
vez e mantenha. O arquivo é segredo: `secrets/` fica fora do Git.
"""

import argparse
import secrets
import sys
from collections.abc import Sequence
from pathlib import Path


def novo_security_toml() -> str:
    # Só hexadecimal: entra numa string TOML sem escape.
    return f'[s3.sse]\nkey = "{secrets.token_hex(32)}"\n'


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gera o security.toml da SSE do SeaweedFS.")
    parser.add_argument("--output", type=Path, default=None, help="arquivo de saída")
    args = parser.parse_args(argv)
    conteudo = novo_security_toml()
    if args.output is None:
        sys.stdout.write(conteudo)
        return 0
    if args.output.exists():
        # Uma chave nova deixaria ilegível o que o SeaweedFS já cifrou com a anterior.
        sys.stderr.write(f"{args.output} já existe; apague-o antes para gerar outra chave.\n")
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Sem chmod 600, como o `jwt_keys`: o compose monta o arquivo como secret com as permissões
    # do host. `secrets/` fica fora do Git.
    args.output.write_text(conteudo, encoding="utf-8")
    sys.stdout.write(f"Chave da SSE do S3 gravada em {args.output}.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
