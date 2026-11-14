.PHONY: check test-all openapi sql-bd migrate up down

check:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy
	uv run lint-imports
	uv run pytest -m "not slow"

test-all:
	uv run pytest

openapi:
	uv run python -m src.tools.export_openapi > contracts/openapi.yaml

# SQL da disciplina de Banco de Dados (spec 011, R11.3): DDL das migrações e consultas, sem banco.
sql-bd: export PYTHONUTF8 = 1
sql-bd:
	uv run python -m src.tools.sql_bd build/sql-bd.sql

migrate:
	uv run alembic revision --autogenerate -m "$(m)"

up:
	docker compose -f docker/compose.yml up -d

down:
	docker compose -f docker/compose.yml down
