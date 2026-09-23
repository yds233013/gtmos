# GTMOS task runner. `make help` lists targets.
SHELL := /bin/bash
API := apps/api
WEB := apps/web
WAREHOUSE := warehouse
DBT_FLAGS := --project-dir $(CURDIR)/$(WAREHOUSE) --profiles-dir $(CURDIR)/$(WAREHOUSE)
API_PORT ?= 8010
WEB_PORT ?= 3010

.PHONY: help setup dev-deps migrate seed reset backtest llm-eval golden-flow api worker web dev up down logs n8n \
        warehouse warehouse-refresh warehouse-docs \
        test test-api test-unit test-web e2e lint typecheck format check clean

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

setup: ## Install backend (uv) and frontend (npm) dependencies
	cd $(API) && uv sync
	cd $(WEB) && npm ci

dev-deps: ## Start Postgres + Redis in Docker (host ports 56432 / 56379)
	docker compose up -d db redis

migrate: ## Apply database migrations
	cd $(API) && uv run alembic upgrade head

seed: ## Load the deterministic DEMO dataset if the database is empty
	cd $(API) && uv run python -m gtmos.seed --if-empty

reset: ## Wipe and reload the DEMO dataset
	cd $(API) && uv run python -m gtmos.seed --reset

backtest: ## Regenerate docs/scoring-backtest.md from the current dataset
	cd $(API) && uv run python -m gtmos.backtest --out ../../docs/scoring-backtest.md

llm-eval: ## Grade the configured research writer against the golden set (no database, no network)
	cd $(API) && uv run python -m gtmos.llmeval --out ../../docs/llm-eval-report.md

golden-flow: ## Run the end-to-end golden scenario against a running stack (add VIA_N8N=1 to route through n8n)
	cd $(API) && uv run python -m gtmos.goldenflow $(if $(VIA_N8N),--via-n8n,)

api: ## Run the API with reload on :$(API_PORT)
	cd $(API) && uv run uvicorn gtmos.main:app --port $(API_PORT) --reload --reload-dir src

worker: ## Run the RQ worker (requires REDIS_URL and QUEUE_BACKEND=redis)
	cd $(API) && uv run python -m gtmos.worker

web: ## Run the web app on :$(WEB_PORT)
	cd $(WEB) && API_INTERNAL_URL=http://127.0.0.1:$(API_PORT) npx next dev -p $(WEB_PORT)

dev: dev-deps migrate seed ## Start deps, migrate, seed, then run API + web together
	@trap 'kill 0' EXIT; $(MAKE) api & $(MAKE) web & wait

up: ## Build and run the full stack in Docker (web :3010, API :8010)
	docker compose up --build -d
	@echo "Web: http://localhost:3010   API docs: http://localhost:8010/docs"

down: ## Stop the Docker stack
	docker compose down

logs: ## Tail Docker logs
	docker compose logs -f --tail=100

n8n: ## Start optional local n8n on :5678 to import integrations/n8n templates
	docker compose --profile n8n up -d n8n

warehouse: ## Build and test the dbt analytics marts into schema `analytics` (needs `make seed`)
	cd $(API) && uv run dbt build $(DBT_FLAGS)

warehouse-refresh: ## Rebuild the marts from scratch (required after `make reset`: the source ids change)
	cd $(API) && uv run dbt build --full-refresh $(DBT_FLAGS)

warehouse-docs: ## Generate the dbt docs site (serve with `dbt docs serve` from warehouse/)
	cd $(API) && uv run dbt docs generate $(DBT_FLAGS)

test: test-api test-web ## Run all backend and frontend tests

test-unit: ## Backend unit tests only (no database)
	cd $(API) && uv run pytest tests/unit

test-api: ## Backend unit + integration tests (needs `make dev-deps`)
	cd $(API) && docker compose exec -T db psql -U gtmos -tc "select 1 from pg_database where datname='gtmos_test'" | grep -q 1 || \
		docker compose exec -T db psql -U gtmos -c "create database gtmos_test"
	cd $(API) && uv run pytest

test-web: ## Frontend unit/component tests
	cd $(WEB) && npm test

e2e: ## Playwright smoke tests against a running stack (E2E_BASE_URL, default :3010)
	cd $(WEB) && npx playwright test

lint: ## Lint backend and frontend
	cd $(API) && uv run ruff check src tests && uv run ruff format --check src tests
	cd $(WEB) && npm run lint

typecheck: ## mypy (strict) + tsc
	cd $(API) && uv run mypy
	cd $(WEB) && npm run typecheck

format: ## Auto-format backend
	cd $(API) && uv run ruff format src tests migrations && uv run ruff check --fix src tests

check: lint typecheck test ## Everything CI would run (plus `cd apps/web && npm run build`)
	cd $(WEB) && npm run build

clean: ## Remove caches and build output
	rm -rf $(API)/.pytest_cache $(API)/.mypy_cache $(API)/.ruff_cache $(WEB)/.next $(WEB)/test-results
