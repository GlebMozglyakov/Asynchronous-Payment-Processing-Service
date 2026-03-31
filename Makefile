PYTHON ?= python

.PHONY: install install-dev run-api run-consumer migrate test test-unit test-integration lint format type-check check up down logs smoke

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

check: lint type-check test

smoke:
	$(PYTHON) -m pytest tests/integration/test_api.py::test_create_payment_and_get_details -q

up:
	docker compose up --build -d

down:
	docker compose down -v

logs:
	docker compose logs -f --tail=200
