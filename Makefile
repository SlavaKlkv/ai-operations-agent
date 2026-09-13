.DEFAULT_GOAL := help
VENV := .venv/bin

.PHONY: help install up down observability migrate run token users test eval lint format check clean

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "\033[36m%-12s\033[0m %s\n", $$1, $$2}'

install:  ## Create the virtualenv and install the project with dev extras
	uv venv --python 3.13
	uv pip install -e ".[dev]"

up:  ## Start PostgreSQL and Redis
	docker compose up -d postgres redis

observability:  ## Start the full stack with Prometheus and Grafana
	docker compose --profile observability up -d
	@echo "Grafana  http://localhost:$${GRAFANA_PORT:-3000}/d/ai-operations-agent"
	@echo "Metrics  http://localhost:8000/metrics"

down:  ## Stop the stack
	docker compose --profile observability down

migrate:  ## Apply database migrations
	$(VENV)/alembic upgrade head

token:  ## Issue an API token: make token EMAIL=you@example.com APPROVE=1
	$(VENV)/python -m app.cli token $(EMAIL) $(if $(APPROVE),--approve,)

users:  ## List users and whether they hold a token
	$(VENV)/python -m app.cli users

run:  ## Run the API with autoreload
	$(VENV)/uvicorn app.main:app --reload --port 8000

test:  ## Run the test suite with coverage
	$(VENV)/pytest --cov=app --cov-report=term-missing

eval:  ## Run the agent evaluation suite
	MCP_ENABLED=false CHECKPOINTER=memory $(VENV)/python -m app.evaluation --quiet

lint:  ## Lint and type-check
	$(VENV)/ruff check .
	$(VENV)/ruff format --check .

format:  ## Auto-fix formatting and lint issues
	$(VENV)/ruff check --fix .
	$(VENV)/ruff format .

check: lint test eval  ## Everything CI runs

clean:  ## Remove caches and build artefacts
	rm -rf .pytest_cache .ruff_cache .mypy_cache htmlcov coverage.xml
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
