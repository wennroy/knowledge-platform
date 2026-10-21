.PHONY: dev test fmt docker-up docker-down install

install:
	cd backend && pip install -e ".[dev]"

dev:
	cd backend && cp -n .env.example .env || true && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

test:
	cd backend && pytest -q

fmt:
	cd backend && ruff check --fix . && ruff format .

docker-up:
	docker compose -f deploy/docker-compose.yml up -d

docker-down:
	docker compose -f deploy/docker-compose.yml down

install-hooks:
	bash deploy/scripts/install-git-hooks.sh

build-spa:
	cd graph-viewer && npm install && npm run build
