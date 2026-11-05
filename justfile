lint:
    uv run ruff check .
    uv run ruff format --check .

fmt:
    uv run ruff format .
    uv run ruff check --fix .

typecheck:
    uv run ty check src

test:
    uv run pytest

test-llm:
    uv run pytest -m llm
