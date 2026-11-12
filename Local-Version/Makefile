.PHONY: dev test lint bench up down

dev:
	docker compose up --build

up:
	docker compose up -d --build

down:
	docker compose down -v --remove-orphans

test:
	cd backend && python -m pytest --cov=app --cov-report=term-missing --cov-fail-under=80
	cd frontend && npm test

lint:
	cd backend && python -m ruff check . ../traffic ../worker ../benchmark
	cd backend && python -m mypy app tests ../traffic ../worker ../benchmark
	cd frontend && npm run lint

bench:
	python benchmark/run_benchmark.py

