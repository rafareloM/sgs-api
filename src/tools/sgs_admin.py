"""Comando de administração `sgs-admin` (spec 002 § Decisões: `argparse`; spec 011, R6.8).

    uv run sgs-admin banco particoes [--meses N]

Subcomandos:
- `banco particoes`: garante as partições mensais do log do banco (`db_change_log`) do mês atual
  até N meses à frente (padrão: 12, o mesmo da migração) com `sp_ensure_monthly_partitions`.
  Mostra cada partição criada e, como aviso, cada mês pulado porque a partição DEFAULT já tem
  registros dele (011/R6.5 a R6.8).

A conexão vem da configuração (`Settings`), como nas migrações: DATABASE_MIGRATION_URL (dono do
banco) ou, na falta dela, DATABASE_URL. O login da API não executa o procedimento (011/R10.1):
sem a URL do dono, o comando sai com erro. O `create-user` da spec 002 (T8) entra como outro
subcomando de primeiro nível.
"""

import argparse
import asyncio
import sys
from collections.abc import Callable, Sequence

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from src.core.config import Settings, load_settings
from src.core.db import create_engine

# O mesmo horizonte da migração 0011_08 (011/R6.7).
MESES_A_FRENTE = 12
SEM_PRIVILEGIO = "42501"  # SQLSTATE insufficient_privilege

_GARANTIR_PARTICOES = text("CALL sp_ensure_monthly_partitions('db_change_log', :meses)")

# Mensagem do servidor: severidade em inglês (não muda com o idioma do banco) e texto.
Mensagem = tuple[str, str]


def main(argv: Sequence[str] | None = None) -> int:
    """Ponto de entrada do `sgs-admin`; devolve o código de saída."""
    args = _parser().parse_args(argv)
    comando: Callable[[argparse.Namespace], int] = args.comando
    return comando(args)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sgs-admin", description="Comandos de administração da API do SGS."
    )
    comandos = parser.add_subparsers(title="comandos", required=True, metavar="COMANDO")

    banco = comandos.add_parser("banco", help="manutenção do banco de dados")
    do_banco = banco.add_subparsers(title="comandos", required=True, metavar="COMANDO")
    particoes = do_banco.add_parser(
        "particoes",
        help="garante as partições mensais do log do banco",
        description=(
            "Garante as partições mensais do log do banco (db_change_log) do mês atual até N"
            " meses à frente, sem apagar nenhuma. Conecta com DATABASE_MIGRATION_URL."
        ),
    )
    particoes.add_argument(
        "--meses",
        type=_meses,
        default=MESES_A_FRENTE,
        metavar="N",
        help=f"meses à frente do atual (padrão: {MESES_A_FRENTE})",
    )
    particoes.set_defaults(comando=_banco_particoes)
    return parser


def _meses(valor: str) -> int:
    try:
        meses = int(valor)
    except ValueError:
        raise argparse.ArgumentTypeError("use um número inteiro") from None
    if meses < 0:
        raise argparse.ArgumentTypeError("use 0 ou mais meses")
    return meses


def _banco_particoes(args: argparse.Namespace) -> int:
    settings = load_settings()
    url = settings.database_migration_url or settings.database_url
    try:
        mensagens = asyncio.run(garantir_particoes(url.get_secret_value(), settings, args.meses))
    except DBAPIError as erro:
        if getattr(erro.orig, "sqlstate", None) != SEM_PRIVILEGIO:
            raise
        # Mensagem fixa: a do erro traz o SQL, e o traceback não ajuda quem administra.
        sys.stderr.write(
            "sgs-admin: o usuário de banco não pode executar sp_ensure_monthly_partitions;"
            " defina DATABASE_MIGRATION_URL com o dono do banco\n"
        )
        return 1
    for severidade, texto in mensagens:
        if severidade == "WARNING":
            sys.stderr.write(f"aviso: {texto}\n")
        else:
            sys.stdout.write(f"{texto}\n")
    sys.stdout.write(
        f"Partições do log do banco garantidas do mês atual até {args.meses} meses à frente.\n"
    )
    return 0


async def garantir_particoes(url: str, settings: Settings, meses: int) -> list[Mensagem]:
    """Executa `sp_ensure_monthly_partitions` numa transação e devolve as mensagens do banco."""
    mensagens: list[Mensagem] = []
    engine = create_engine(url, settings, pooled=False)
    try:
        async with engine.begin() as conexao:
            # O procedimento fala por RAISE NOTICE/WARNING, que chegam ao asyncpg fora do
            # resultado da instrução, por um ouvinte da conexão.
            bruta = await conexao.get_raw_connection()
            if bruta.driver_connection is None:
                raise RuntimeError("conexão com o banco sem o driver asyncpg")
            bruta.driver_connection.add_log_listener(
                lambda _conexao, msg: mensagens.append((msg.severity_en, msg.message))
            )
            await conexao.execute(_GARANTIR_PARTICOES, {"meses": meses})
    finally:
        await engine.dispose()
    return mensagens
