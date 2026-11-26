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

    uv run sgs-admin create-user --username admin --nome "Administrador" [--papel ADMIN_TI]

- `create-user` (spec 002, T8): cria um usuário local com senha Argon2id e uma atribuição de
  papel, e grava `usuario.criado` e `papel.atribuido` na mesma transação (AGENTS.md, regra 5). A
  senha vem de `SGS_SENHA_INICIAL` ou é pedida no terminal (duas vezes); nunca vai para o log.
  Conecta com DATABASE_URL (o login da API).

    uv run sgs-admin auditoria ancorar
    uv run sgs-admin auditoria verificar [--ancora arquivo.json]

- `auditoria ancorar` (spec 013, T9; R5.4): verifica a cadeia inteira e, se estiver íntegra,
  imprime a âncora em JSON (versão, `cadeia_id`, id e hash do último evento, total, instante em
  UTC e nome do banco) para guardar fora do banco. Cadeia vazia: código 2; divergente: código 1.
- `auditoria verificar` (013/R5.12): a mesma verificação da API, direto no banco, sem a API,
  e com a âncora, se dada. Imprime o resultado em JSON. Código 0 se íntegra, 1 se não, 2 se a
  âncora é ilegível ou de outro formato.

Os dois são só de leitura (REPEATABLE READ, READ ONLY) e não gravam evento nenhum, nem
`auditoria.verificada`: dá para usá-los numa cópia restaurada em outro servidor sem alterá-la.
Conectam com DATABASE_URL.

    uv run sgs-admin diretorio testar [--url URL] [--ca ARQUIVO]

- `diretorio testar` (spec 004, T11; R1.13): conexão, TLS e bind da conta de serviço com a
  configuração LDAP_*, ou com --url e --ca por cima dela, sem gravar nada. Responde "ok" ou o
  motivo genérico (certificado, conexao, credencial). Código 0: ok; 1: recusado; 2: configuração
  inválida. A senha e a mensagem do `ldap3` nunca vão para a saída.
"""

import argparse
import asyncio
import dataclasses
import getpass
import json
import os
import re
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import Settings, load_settings
from src.core.db import create_engine
from src.modules.access.application.autorizacao import UsuarioAtual
from src.modules.access.domain.authorization import Global
from src.modules.audit.application.consultar import (
    Ancora,
    gerar_ancora,
    verificar_cadeia,
)
from src.modules.audit.infrastructure.consultas import SqlConsultasDeAuditoria

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

    criar = comandos.add_parser(
        "create-user",
        help="cria um usuário local (o primeiro administrador)",
        description=(
            "Cria um usuário local com senha Argon2id e um papel. A senha vem de"
            " SGS_SENHA_INICIAL ou é pedida no terminal. Conecta com DATABASE_URL."
        ),
    )
    criar.add_argument("--username", required=True)
    criar.add_argument("--nome", required=True, help="nome de exibição")
    criar.add_argument("--email", default=None)
    criar.add_argument("--papel", default="ADMIN_TI", help="código do papel (padrão: ADMIN_TI)")
    criar.add_argument(
        "--escopo-tipo", default="global", choices=("global", "area", "distrito", "unidade")
    )
    criar.add_argument("--escopo-id", default=None)
    criar.set_defaults(comando=_create_user)

    seed = comandos.add_parser("seed", help="dados de demonstração (spec 010)")
    do_seed = seed.add_subparsers(title="comandos", required=True, metavar="COMANDO")
    demo = do_seed.add_parser(
        "demo",
        help="carrega a massa de demonstração (idempotente; recusada em prod)",
        description=(
            "Carrega referências, unidades, equipamentos, serviços e 30 usuários fictícios de"
            " seeds/demo/. Rodar de novo não duplica. A senha dos usuários vem de SGS_SEED_SENHA"
            " ou é gerada e mostrada uma vez. Conecta com DATABASE_URL."
        ),
    )
    demo.set_defaults(comando=_seed_demo)

    auditoria = comandos.add_parser("auditoria", help="âncora e verificação da trilha (spec 013)")
    da_auditoria = auditoria.add_subparsers(title="comandos", required=True, metavar="COMANDO")
    ancorar = da_auditoria.add_parser(
        "ancorar",
        help="verifica a cadeia e imprime a âncora em JSON (só leitura)",
        description=(
            "Verifica a trilha inteira e, se ela estiver íntegra, imprime a âncora em JSON para"
            " guardar fora do banco. Não grava nada. Conecta com DATABASE_URL."
        ),
    )
    ancorar.set_defaults(comando=_auditoria_ancorar)
    verificar = da_auditoria.add_parser(
        "verificar",
        help="verifica a cadeia direto no banco, sem a API (só leitura)",
        description=(
            "Verifica a trilha direto no banco, com a âncora se dada, e imprime o resultado em"
            " JSON. Código 0: íntegra; 1: divergente; 2: âncora inválida. Não grava nada."
        ),
    )
    verificar.add_argument("--ancora", type=Path, default=None, metavar="ARQUIVO")
    verificar.set_defaults(comando=_auditoria_verificar)

    diretorio = comandos.add_parser("diretorio", help="diretório LDAP (spec 004)")
    do_diretorio = diretorio.add_subparsers(title="comandos", required=True, metavar="COMANDO")
    testar = do_diretorio.add_parser(
        "testar",
        help="testa a conexão, o TLS e o bind da conta de serviço (não grava nada)",
        description=(
            "Tenta a conexão e o bind da conta de serviço com a configuração LDAP_*, ou com"
            " --url e --ca por cima dela. Responde ok ou o motivo: certificado, conexao ou"
            " credencial. Código 0: ok; 1: recusado; 2: configuração inválida."
        ),
    )
    testar.add_argument("--url", default=None, help="no lugar de LDAP_URL")
    testar.add_argument("--ca", default=None, metavar="ARQUIVO", help="no lugar de LDAP_CA_FILE")
    testar.set_defaults(comando=_diretorio_testar)
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


SENHA_MINIMA = 12


def _senha() -> str | None:
    senha = os.environ.get("SGS_SENHA_INICIAL")
    if senha is None:
        senha = getpass.getpass("Senha: ")
        if senha != getpass.getpass("Repita a senha: "):
            sys.stderr.write("sgs-admin: as senhas não conferem\n")
            return None
    if len(senha) < SENHA_MINIMA:
        sys.stderr.write(f"sgs-admin: use uma senha com ao menos {SENHA_MINIMA} caracteres\n")
        return None
    return senha


def _create_user(args: argparse.Namespace) -> int:
    senha = _senha()
    if senha is None:
        return 1
    settings = load_settings()
    try:
        usuario_id = asyncio.run(
            criar_usuario(
                settings.database_url.get_secret_value(),
                settings,
                username=args.username,
                nome=args.nome,
                email=args.email,
                senha=senha,
                papel=args.papel,
                escopo_tipo=args.escopo_tipo,
                escopo_id=args.escopo_id,
            )
        )
    except ValueError as erro:
        sys.stderr.write(f"sgs-admin: {erro}\n")
        return 1
    sys.stdout.write(
        f"Usuário {args.username} criado (id {usuario_id}) com o papel {args.papel}.\n"
    )
    return 0


async def criar_usuario(
    url: str,
    settings: Settings,
    *,
    username: str,
    nome: str,
    email: str | None,
    senha: str,
    papel: str,
    escopo_tipo: str = "global",
    escopo_id: str | None = None,
) -> str:
    """Cria o usuário e a atribuição numa transação, com auditoria. Levanta `ValueError` com uma
    mensagem para o terminal se o usuário já existe, o papel não existe ou o escopo não confere."""

    from src.core.ids import uuid7
    from src.modules.access.domain.atribuicoes import Atribuicao
    from src.modules.access.infrastructure.repository import SqlRepositorioDeAtribuicoes
    from src.modules.audit.application.registrar import Ator, Entidade, registrar
    from src.modules.audit.infrastructure.repository import SqlAuditStore
    from src.modules.identity.domain.users import User, UserSource
    from src.modules.identity.infrastructure.passwords import Argon2PasswordHasher
    from src.modules.identity.infrastructure.repository import SqlUserRepository

    engine = create_engine(url, settings, pooled=False)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as sessao, sessao.begin():
            usuarios = SqlUserRepository(sessao)
            if await usuarios.get_by_username(username) is not None:
                raise ValueError(f"já existe o usuário {username!r}")
            atribuicoes = SqlRepositorioDeAtribuicoes(sessao)
            definicao = await atribuicoes.papel(papel)
            if definicao is None:
                raise ValueError(f"papel inexistente: {papel!r}")
            if escopo_tipo != definicao.escopo_exigido:
                raise ValueError(f"o papel {papel} exige escopo {definicao.escopo_exigido}")
            if escopo_tipo != "global" and (
                escopo_id is None or not await atribuicoes.escopo_existe(escopo_tipo, escopo_id)
            ):
                raise ValueError("escopo inexistente")
            usuario = User(
                id=uuid7(),
                username=username,
                display_name=nome,
                source=UserSource.LOCAL,
                password_hash=Argon2PasswordHasher().hash(senha),
                email=email,
            )
            await usuarios.add(usuario)
            atribuicao_id = uuid7()
            await atribuicoes.inserir(
                Atribuicao(
                    id=atribuicao_id,
                    user_id=usuario.id,
                    papel=papel,
                    scope_type=escopo_tipo,
                    scope_id=escopo_id if escopo_tipo != "global" else None,
                    origin="direct",
                    valid_until=None,
                    granted_by=None,
                )
            )
            loja = SqlAuditStore(sessao)
            # 013/R1.1, R1.2: comando administrativo, sem usuário humano atribuído.
            sistema = Ator(tipo="cli_admin", origem="sgs-admin create-user")
            entidade = Entidade(tipo="usuario", id=str(usuario.id))
            await registrar(
                loja,
                acao="usuario.criado",
                ator=sistema,
                entidade=entidade,
                metadados={"username": usuario.username, "origem": "sgs-admin create-user"},
            )
            await registrar(
                loja,
                acao="papel.atribuido",
                ator=sistema,
                entidade=entidade,
                metadados={
                    "atribuicao_id": str(atribuicao_id),
                    "papel": papel,
                    "escopo_tipo": escopo_tipo,
                    "escopo_id": escopo_id,
                    "origem": "sgs-admin create-user",
                },
            )
    finally:
        await engine.dispose()
    return str(usuario.id)


def _seed_demo(args: argparse.Namespace) -> int:
    from src.tools.seed_demo import SeedRecusado, carregar

    settings = load_settings()
    try:
        contagem = asyncio.run(
            carregar(
                settings.database_url.get_secret_value(),
                settings,
                senha=os.environ.get("SGS_SEED_SENHA"),
            )
        )
    except SeedRecusado as erro:
        sys.stderr.write(f"sgs-admin: {erro}\n")
        return 1
    for tipo in sorted(set(contagem.criados) | set(contagem.pulados)):
        sys.stdout.write(
            f"{tipo}: {contagem.criados.get(tipo, 0)} criados,"
            f" {contagem.pulados.get(tipo, 0)} já existiam\n"
        )
    if contagem.senha_gerada is not None:
        sys.stdout.write(
            "Senha gerada para os usuários demo.* (anote, não será mostrada de novo):"
            f" {contagem.senha_gerada}\n"
        )
    return 0


# --------------------------------------------------------------- auditoria (spec 013, T9)

VERSAO_DA_ANCORA = 1
_HASH = re.compile(r"[0-9a-f]{64}")
CADEIA_VAZIA = 2
DIVERGENTE = 1
ANCORA_INVALIDA = 2


class AncoraInvalidaError(ValueError):
    pass


def _auditor_do_sistema() -> UsuarioAtual:
    """O comando lê a trilha como o Auditor, em escopo global; não é uma pessoa e não grava."""
    return UsuarioAtual(
        id=UUID(int=0), sessao_id=UUID(int=0), permissoes={"auditoria:read": (Global(),)}
    )


async def ancorar_cadeia(url: str, settings: Settings) -> tuple[int, str]:
    """(código de saída, texto). Com a cadeia íntegra, o texto é a âncora em JSON."""
    engine = create_engine(url, settings, pooled=False)
    try:
        async with AsyncSession(engine) as sessao:
            resultado, ancora = await gerar_ancora(
                _auditor_do_sistema(), consultas=SqlConsultasDeAuditoria(sessao)
            )
    finally:
        await engine.dispose()
    if ancora is None and resultado.integra:
        return CADEIA_VAZIA, "cadeia vazia: nada a ancorar"
    if ancora is None:
        return DIVERGENTE, f"cadeia divergente, sem âncora: {resultado.motivo}"
    documento = {
        "versao": ancora.versao,
        "cadeia_id": ancora.cadeia_id,
        "id": ancora.id,
        "hash": ancora.hash,
        "total": ancora.total,
        "instante": datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z"),
        "banco": ancora.banco,
    }
    return 0, json.dumps(documento, ensure_ascii=False)


def ler_ancora(arquivo: Path) -> Ancora:
    """A âncora de um arquivo JSON gerado por `ancorar`; formato, versão e campos conferidos."""
    try:
        dados = json.loads(arquivo.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as erro:
        raise AncoraInvalidaError(
            f"não foi possível ler a âncora: {erro.__class__.__name__}"
        ) from None
    if not isinstance(dados, dict) or dados.get("versao") != VERSAO_DA_ANCORA:
        raise AncoraInvalidaError(
            f"âncora de formato desconhecido (esperada versão {VERSAO_DA_ANCORA})"
        )
    cadeia_id, id_, hash_ = dados.get("cadeia_id"), dados.get("id"), dados.get("hash")
    if not (isinstance(cadeia_id, str) and _HASH.fullmatch(cadeia_id)):
        raise AncoraInvalidaError("cadeia_id inválido")
    if not (isinstance(hash_, str) and _HASH.fullmatch(hash_)):
        raise AncoraInvalidaError("hash inválido")
    if not isinstance(id_, int) or isinstance(id_, bool) or id_ < 1:
        raise AncoraInvalidaError("id inválido")
    return Ancora(cadeia_id=cadeia_id, id=id_, hash=hash_)


async def verificar_offline(url: str, settings: Settings, ancora: Ancora | None) -> tuple[int, str]:
    """(código de saída, resultado em JSON). A mesma `verificar_cadeia` da API, sem
    `registrar_execucao`: nada é gravado."""
    engine = create_engine(url, settings, pooled=False)
    try:
        async with AsyncSession(engine) as sessao:
            resultado = await verificar_cadeia(
                _auditor_do_sistema(),
                None,
                None,
                consultas=SqlConsultasDeAuditoria(sessao),
                ancora=ancora,
            )
    finally:
        await engine.dispose()
    codigo = 0 if resultado.integra else DIVERGENTE
    return codigo, json.dumps(dataclasses.asdict(resultado), ensure_ascii=False)


def _auditoria_ancorar(_args: argparse.Namespace) -> int:
    settings = load_settings()
    codigo, texto = asyncio.run(ancorar_cadeia(settings.database_url.get_secret_value(), settings))
    (sys.stdout if codigo == 0 else sys.stderr).write(
        f"{texto}\n" if codigo == 0 else f"sgs-admin: {texto}\n"
    )
    return codigo


def _auditoria_verificar(args: argparse.Namespace) -> int:
    ancora = None
    if args.ancora is not None:
        try:
            ancora = ler_ancora(args.ancora)
        except AncoraInvalidaError as erro:
            sys.stderr.write(f"sgs-admin: {erro}\n")
            return ANCORA_INVALIDA
    settings = load_settings()
    codigo, texto = asyncio.run(
        verificar_offline(settings.database_url.get_secret_value(), settings, ancora)
    )
    sys.stdout.write(f"{texto}\n")
    return codigo


# --------------------------------------------------------------- diretório (spec 004, T11)

CONFIGURACAO_INVALIDA = 2


async def conferir_diretorio(
    settings: Settings, *, url: str | None = None, ca: str | None = None
) -> tuple[int, str]:
    """(código de saída, texto) do teste de conexão e bind da conta de serviço. Só o motivo
    genérico vai para o texto: nada da senha nem da mensagem do `ldap3`."""
    from src.modules.identity.infrastructure.ldap3_directory import Ldap3Directory, LdapConfig

    trocas = {"ldap_url": url, "ldap_ca_file": ca}
    settings = settings.model_copy(update={k: v for k, v in trocas.items() if v is not None})
    if settings.ldap_url is None:
        return CONFIGURACAO_INVALIDA, "LDAP_URL: o LDAP está desligado; defina-a ou use --url"
    problemas = settings.problemas_do_ldap()
    if problemas:
        return CONFIGURACAO_INVALIDA, "; ".join(problemas)
    config = LdapConfig.from_settings(settings)
    if config is None:  # pragma: no cover - LDAP_URL conferida acima
        return CONFIGURACAO_INVALIDA, "LDAP_URL: o LDAP está desligado"
    motivo = await Ldap3Directory(config).testar()
    return (0, "ok") if motivo == "ok" else (1, f"diretório recusado: {motivo}")


def _diretorio_testar(args: argparse.Namespace) -> int:
    codigo, texto = asyncio.run(conferir_diretorio(load_settings(), url=args.url, ca=args.ca))
    (sys.stdout if codigo == 0 else sys.stderr).write(
        f"{texto}\n" if codigo == 0 else f"sgs-admin: {texto}\n"
    )
    return codigo
