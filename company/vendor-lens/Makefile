.PHONY: dev build up down logs test

dev:        ## Start backend dev server locally (no Docker)
	cd backend && uvicorn app.main:app --reload --port 8002

dev-fe:     ## Start Next.js dev server
	cd frontend && npm run dev -- --port 3001

build:      ## Build Docker images
	docker compose build

up:         ## Start all services
	docker compose up -d

down:       ## Stop all services
	docker compose down

logs:       ## Tail logs
	docker compose logs -f

test:       ## Run backend tests
	cd backend && python -m pytest -q

migrate:    ## Run DB schema creation
	cd backend && python -c "import asyncio; from app.database import init_db; asyncio.run(init_db())"
