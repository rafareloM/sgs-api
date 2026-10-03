.PHONY: check test-all openapi migrate up down

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

migrate:
	uv run alembic revision --autogenerate -m "$(m)"

up:
	docker compose -f docker/compose.yml up -d

down:
	docker compose -f docker/compose.yml down
