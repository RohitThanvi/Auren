.PHONY: help install up down migrate api-run api-check api-test agent-check web-dev web-check contracts check

ENV_FILE := ../../.env

help: ## List targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "%-14s %s\n", $$1, $$2}'

install: ## Install all dependencies
	cd apps/api && uv sync
	cd apps/agent && uv sync
	npm ci

up: ## Start PostgreSQL, Redis, migrations and the API in Docker
	docker compose up --build -d

down: ## Stop the Docker stack
	docker compose down

migrate: ## Apply database migrations to the database in .env
	cd apps/api && uv run --env-file $(ENV_FILE) alembic upgrade head

api-run: ## Run the API on the host (needs Postgres and Redis, e.g. `docker compose up -d postgres redis`)
	cd apps/api && uv run --env-file $(ENV_FILE) python -m auren_api

api-check: ## Lint, format check, type check API
	cd apps/api && uv run ruff check . && uv run ruff format --check . && uv run pyright

api-test: ## API tests with coverage (real PostgreSQL and Redis required)
	cd apps/api && uv run --env-file $(ENV_FILE) pytest --cov

agent-check: ## Lint, type check and test the provider agent
	cd apps/agent && uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest --cov

web-dev: ## Run the frontend dev server
	npm -w apps/web run dev

web-check: ## Lint, format check, type check, test and build the frontend
	npm -w apps/web run lint && npm -w apps/web run format:check && npm -w apps/web run typecheck && npm -w apps/web run test:coverage && npm -w apps/web run build

contracts: ## Regenerate shared contracts from the API (OpenAPI -> TypeScript)
	cd apps/api && uv run --env-file $(ENV_FILE) python scripts/export_openapi.py ../../packages/contracts/openapi.json
	npm -w packages/contracts run generate

check: api-check api-test agent-check web-check ## Run every check
