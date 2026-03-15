.PHONY: dev install lint format check

dev:
	uv run -- python -m uvicorn linguee_api.main:app --reload

install:
	uv venv && uv pip install -e ".[dev]"

lint:
	uv run ruff check src/

format:
	uv run ruff format src/

check: lint
	uv run ruff format --check src/
