PYTHON ?= python

.PHONY: install install-dev run-api run-consumer migrate test test-unit test-integration lint format type-check up down logs

install:
	$(PYTHON) -m pip install .

install-dev:
	$(PYTHON) -m pip install -e ".[dev]"

run-api:
	$(PYTHON) -m app.main

run-consumer:
	$(PYTHON) -m app.consumer

migrate:
	$(PYTHON) -m alembic upgrade head

test:
	$(PYTHON) -m pytest -q

test-unit:
	$(PYTHON) -m pytest -m unit -q

test-integration:
	$(PYTHON) -m pytest -m integration -q

lint:
	$(PYTHON) -m ruff check .

format:
	$(PYTHON) -m ruff format .

type-check:
	$(PYTHON) -m mypy .

up:
	docker compose up --build -d

down:
	docker compose down -v

logs:
	docker compose logs -f --tail=200
