"""Script para executar o seed de dados da Etapa 02 no PostgreSQL (`make seed`)."""

import asyncio
import sys
from pathlib import Path

from sqlalchemy import text

from src.core.config import Settings, load_settings
from src.core.db import create_engine

DEFAULT_SEED_FILE = (
    Path(__file__).resolve().parents[1] / "resources" / "seeds" / "2_SQL_Insercao_Dados.sql"
)


async def seed_database(
    seed_file_path: Path | str | None = None,
    database_url: str | None = None,
    settings: Settings | None = None,
) -> dict[str, int]:
    path = Path(seed_file_path) if seed_file_path else DEFAULT_SEED_FILE
    if not path.is_file():
        raise FileNotFoundError(f"Arquivo de seed não encontrado: {path}")

    sql_content = path.read_text(encoding="utf-8")
    effective_settings = settings or load_settings()
    if database_url is not None:
        url = database_url
    else:
        url_secret = effective_settings.database_migration_url or effective_settings.database_url
        url = url_secret.get_secret_value()

    engine = create_engine(url, effective_settings, pooled=False)

    try:
        async with engine.begin() as conn:
            raw_conn = await conn.get_raw_connection()
            driver_conn = raw_conn.driver_connection
            if driver_conn is None:
                raise RuntimeError("Conexão com driver de banco indisponível.")
            await driver_conn.execute(sql_content)

        table_queries = {
            "perfil": text("SELECT COUNT(*) FROM perfil"),
            "unidade_saude": text("SELECT COUNT(*) FROM unidade_saude"),
            "usuario": text("SELECT COUNT(*) FROM usuario"),
            "equipamento": text("SELECT COUNT(*) FROM equipamento"),
            "alteracao": text("SELECT COUNT(*) FROM alteracao"),
        }
        counts: dict[str, int] = {}
        async with engine.connect() as conn:
            for name, query in table_queries.items():
                result = await conn.execute(query)
                counts[name] = int(result.scalar_one())

        return counts
    finally:
        await engine.dispose()


def main() -> None:
    seed_file = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    sys.stdout.write(
        f"Iniciando seed do banco de dados a partir de: {seed_file or DEFAULT_SEED_FILE}...\n"
    )
    try:
        counts = asyncio.run(seed_database(seed_file))
        sys.stdout.write("Seed concluído com sucesso! Registros por tabela:\n")
        for table, count in counts.items():
            sys.stdout.write(f"  - {table}: {count} registros\n")
        total = sum(counts.values())
        sys.stdout.write(f"Total: {total} registros inseridos.\n")
    except Exception as exc:
        sys.stderr.write(f"Erro ao executar seed: {exc}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
