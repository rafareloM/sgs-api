"""Carregador do DDL escrito à mão das migrações (spec 011, R11.1 e R11.2; ADR-0009).

Uso numa revisão do Alembic (`migrations/versions/<revisão>_<nome>.py`):

    from migrations.sql_loader import executar_sql

    def upgrade() -> None:
        executar_sql("0011_03", "01_sgs_owner.sql")
        executar_sql("0011_03", "02_ix_audit_log_entity.sql")

Regras do arquivo `migrations/sql/<revisão>/<arquivo>`:
- Exatamente uma instrução SQL, com ou sem `;` no fim: o asyncpg prepara cada instrução, e duas
  no mesmo texto falham. Um `;` dentro de comentário, string (`'...'`, `E'...'`), identificador
  entre aspas ou corpo `$$ ... $$`/`$tag$ ... $tag$` não conta. Arquivo vazio, com duas
  instruções ou com algum desses trechos sem fechamento levanta `ArquivoSqlError` antes de
  qualquer coisa ir para o banco.
- O cabeçalho em comentário (objetivo, justificativa, uso, requisito) vai junto com a instrução;
  o que vier depois do `;` final é descartado.
- Todo `:` é escapado antes do `text()`: `'HH24:MI'`, o `:=` do PL/pgSQL e um `:id` citado no
  cabeçalho chegam ao banco como estão. Por isso o arquivo não recebe parâmetros (DDL não tem
  valor vindo de fora).
- A mesma chamada serve com banco (`op.execute`) e no modo offline (`alembic upgrade head
  --sql`), que imprime a instrução com o cabeçalho.
- Arquivo de revisão já aplicada não é editado: a mudança vai numa revisão nova.
"""

import re
from pathlib import Path

from alembic import op
from sqlalchemy import text

DIRETORIO_SQL = Path(__file__).resolve().parent / "sql"

_STRING = re.compile(r"'(?:[^']|'')*'")
_STRING_COM_ESCAPE = re.compile(r"[eE]'(?:[^'\\]|\\.|'')*'", re.DOTALL)
_IDENTIFICADOR_ENTRE_ASPAS = re.compile(r'"(?:[^"]|"")*"')
_DELIMITADOR_DOLAR = re.compile(r"\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$")
_CORPO_ENTRE_DOLARES = re.compile(r"(\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$).*?\1", re.DOTALL)


class ArquivoSqlError(ValueError):
    """O arquivo não tem exatamente uma instrução completa."""


def executar_sql(revisao: str, arquivo: str) -> None:
    """Executa a instrução de `migrations/sql/<revisao>/<arquivo>` na migração em andamento."""
    conteudo = (DIRETORIO_SQL / revisao / arquivo).read_text(encoding="utf-8")
    instrucao = _instrucao_unica(conteudo, origem=f"{revisao}/{arquivo}")
    op.execute(text(instrucao.replace(":", r"\:")))


def _instrucao_unica(conteudo: str, origem: str) -> str:
    """Devolve o texto até o `;` que encerra a única instrução, com o cabeçalho."""
    instrucoes = 0
    fim = len(conteudo)
    tem_conteudo = False
    i = 0
    while i < len(conteudo):
        if conteudo.startswith("--", i):
            quebra = conteudo.find("\n", i)
            i = len(conteudo) if quebra == -1 else quebra
            continue
        if conteudo.startswith("/*", i):
            i = _fim_do_comentario_de_bloco(conteudo, i, origem)
            continue
        fim_do_literal = _fim_do_literal(conteudo, i, origem)
        if fim_do_literal is not None:
            i = fim_do_literal
            tem_conteudo = True
            continue
        if conteudo[i] == ";":
            if tem_conteudo:
                instrucoes += 1
                if instrucoes == 1:
                    fim = i
            tem_conteudo = False
        elif not conteudo[i].isspace():
            tem_conteudo = True
        i += 1
    if tem_conteudo:
        instrucoes += 1
    if instrucoes == 0:
        raise ArquivoSqlError(f"{origem}: nenhuma instrução no arquivo")
    if instrucoes > 1:
        raise ArquivoSqlError(f"{origem}: mais de uma instrução no arquivo")
    return conteudo[:fim].rstrip()


def _fim_do_comentario_de_bloco(conteudo: str, inicio: int, origem: str) -> int:
    """Posição logo depois do `*/` que fecha o comentário (no PostgreSQL, eles se aninham)."""
    profundidade = 0
    i = inicio
    while i < len(conteudo):
        if conteudo.startswith("/*", i):
            profundidade += 1
            i += 2
        elif conteudo.startswith("*/", i):
            profundidade -= 1
            i += 2
            if profundidade == 0:
                return i
        else:
            i += 1
    raise ArquivoSqlError(f"{origem}: comentário /* sem fechamento")


def _fim_do_literal(conteudo: str, i: int, origem: str) -> int | None:
    """Se em `i` começa string, identificador entre aspas ou corpo entre `$`, onde ele acaba."""
    caractere = conteudo[i]
    if caractere in "eE" and conteudo.startswith("'", i + 1) and not _no_identificador(conteudo, i):
        padrao, nome = _STRING_COM_ESCAPE, "string"
    elif caractere == "'":
        padrao, nome = _STRING, "string"
    elif caractere == '"':
        padrao, nome = _IDENTIFICADOR_ENTRE_ASPAS, "identificador entre aspas"
    elif (
        caractere == "$"
        and _DELIMITADOR_DOLAR.match(conteudo, i)
        and not _no_identificador(conteudo, i)
    ):
        padrao, nome = _CORPO_ENTRE_DOLARES, "corpo entre $"
    else:
        return None
    literal = padrao.match(conteudo, i)
    if literal is None:
        raise ArquivoSqlError(f"{origem}: {nome} sem fechamento")
    return literal.end()


def _no_identificador(conteudo: str, i: int) -> bool:
    """`E'` e `$tag$` só abrem literal fora de um identificador (`type'x'`, `a$b$`)."""
    return i > 0 and (conteudo[i - 1].isalnum() or conteudo[i - 1] in "_$")
