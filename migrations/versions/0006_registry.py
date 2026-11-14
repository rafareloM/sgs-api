"""registry: cadastro de unidades, equipamentos e serviços (spec 006, T1; spec 011, T2).

Completa as tabelas de docs/architecture/modelo-dados.md § 2 conforme o design da 006 § Modelo e
o da 011 § Na 0006. Todo o DDL do upgrade está em `migrations/sql/0006/`, uma instrução por
arquivo, com o cabeçalho que explica cada objeto (ADR-0009, 011/R11.1):

- extensões `unaccent` e `pg_trgm` e a `fn_normalize_name` (IMMUTABLE, `search_path` fixo,
  EXECUTE só para `sgs_app`), criada antes da coluna gerada que a usa (011/R5.1, R5.2, R10.1);
- referências: `districts` e `technical_areas` (da 0003) ganham exclusão lógica; `unit_types`,
  `equipment_types` e `service_types` nascem aqui (006/R7.1, R7.2);
- `health_units` (stub da 0003) ganha as colunas do modelo, `name_normalized` gerada,
  `version`, `pending_issues`, as FKs e os índices únicos (CNES parcial, nome por distrito) e de
  trigramas (006/R1.3, R1.4, R2.2);
- `equipments` e `services` com as FKs da Etapa 02: SET NULL, ON UPDATE CASCADE e RESTRICT
  (011/R9.1 a R9.3);
- seed das referências, por último.

Revision ID: 0006
Revises: 0003_1
Create Date: 2026-11-07
"""

from collections.abc import Sequence

from alembic import op

from migrations.sql_loader import executar_sql

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0003_1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REVISAO = "0006"

# Ordem de execução (a numeração dos arquivos): a função de normalização antes da coluna gerada
# que a usa, as referências antes das tabelas que apontam para elas, e o seed por último.
ARQUIVOS = (
    "01_unaccent.sql",
    "02_pg_trgm.sql",
    "03_fn_normalize_name.sql",
    "04_fn_normalize_name_revoke_public.sql",
    "05_fn_normalize_name_grant_sgs_app.sql",
    "06_districts.sql",
    "07_technical_areas.sql",
    "08_unit_types.sql",
    "09_equipment_types.sql",
    "10_service_types.sql",
    "11_health_units.sql",
    "12_health_units_fks.sql",
    "13_ix_health_units_cnes.sql",
    "14_ix_health_units_district_id_name_normalized.sql",
    "15_ix_health_units_name_normalized_trgm.sql",
    "16_equipments.sql",
    "17_services.sql",
    "18_seed_districts.sql",
    "19_seed_technical_areas.sql",
    "20_seed_unit_types.sql",
    "21_seed_equipment_types.sql",
    "22_seed_service_types.sql",
)


def upgrade() -> None:
    for arquivo in ARQUIVOS:
        executar_sql(REVISAO, arquivo)


def downgrade() -> None:
    # Desfaz, na ordem inversa, só o que a 0006 acrescentou: o que a 0003 criou fica como estava
    # (as tabelas de distritos e áreas técnicas perdem só a coluna nova e as linhas semeadas).
    op.execute("DROP TABLE services")
    op.execute("DROP TABLE equipments")
    op.execute(
        "ALTER TABLE health_units"
        " DROP CONSTRAINT fk_health_units_unit_type_id_unit_types,"
        " DROP CONSTRAINT fk_health_units_district_id_districts,"
        " DROP COLUMN updated_at, DROP COLUMN created_at, DROP COLUMN version,"
        " DROP COLUMN pending_issues, DROP COLUMN status, DROP COLUMN longitude,"
        " DROP COLUMN latitude, DROP COLUMN opening_hours, DROP COLUMN phone,"
        " DROP COLUMN neighborhood, DROP COLUMN address, DROP COLUMN cep,"
        " DROP COLUMN manager_name, DROP COLUMN name_normalized, DROP COLUMN name,"
        " DROP COLUMN cnes"
    )
    op.execute(
        "DELETE FROM districts WHERE code IN"
        " ('DS-I', 'DS-II', 'DS-III', 'DS-IV', 'DS-V', 'DS-VI', 'DS-VII', 'DS-VIII')"
    )
    op.execute("DROP TABLE service_types")
    op.execute("DROP TABLE equipment_types")
    op.execute("DROP TABLE unit_types")
    op.execute(
        "DELETE FROM technical_areas WHERE code IN ('SAUDE_MENTAL', 'SAUDE_BUCAL', 'APS', 'MAC')"
    )
    op.execute("ALTER TABLE technical_areas DROP COLUMN is_active")
    op.execute("ALTER TABLE districts DROP COLUMN is_active")
    op.execute("DROP FUNCTION fn_normalize_name(text)")
    op.execute("DROP EXTENSION pg_trgm")
    op.execute("DROP EXTENSION unaccent")
