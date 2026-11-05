export API_PORT := env_var_or_default("API_PORT", "8000")

up:
    docker compose up -d --build --wait api worker

# NVIDIA laptop: (re)install Docker Model Runner with CUDA, then start the stack.
up-gpu:
    docker model reinstall-runner --gpu cuda
    docker compose up -d --build --wait api worker

down:
    docker compose -f docker-compose.yml -f compose.replay.yaml down -v

demo: up
    ./scripts/demo.sh

# Runs without the model: LLM outputs come from fixtures/llm_replay.
demo-replay:
    docker compose -f docker-compose.yml -f compose.replay.yaml up -d --build --wait api worker
    ./scripts/demo.sh

logs:
    docker compose logs -f --tail=100

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

record-replay:
    uv run python scripts/record_replay.py

# Golden-set evals: mode = cascade | llm | rules (llm/cascade need the model runner).
eval mode="cascade":
    uv run python -m evals.run_evals --mode {{mode}}
