"""Consultas escritas à mão em arquivos `.sql` (ADR-0009; design da 011 § Onde fica o SQL).

Cada módulo guarda as suas em `src/modules/<módulo>/infrastructure/sql/<nome>.sql`, com o
cabeçalho de objetivo, justificativa, uso e requisito, e as carrega uma vez, na importação do
repositório:

    _SQL = Path(__file__).parent / "sql"
    _INSERIR = consulta(_SQL / "insert_health_unit.sql")

O texto vai inteiro para `text()`: os valores entram só como parâmetros nomeados (`:nome`),
nunca interpolados. Por isso o cabeçalho não pode ter `:` colado a uma palavra, que o SQLAlchemy
leria como parâmetro; casts usam `CAST(... AS ...)`.
"""

from pathlib import Path

from sqlalchemy import TextClause, text


def consulta(arquivo: Path) -> TextClause:
    """Lê o arquivo (UTF-8) e devolve a consulta pronta para `session.execute`."""
    return text(arquivo.read_text(encoding="utf-8"))
