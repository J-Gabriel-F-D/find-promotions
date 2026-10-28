PYTHON ?= .venv/bin/python
PYTEST = $(PYTHON) -m pytest

.PHONY: test test-unit test-integration test-e2e test-security test-functional test-regression test-coverage test-all lint format

test:
	$(PYTEST) tests

test-unit:
	$(PYTEST) tests/unit

test-integration:
	$(PYTEST) -m integration

test-e2e:
	$(PYTEST) -m e2e

test-security:
	$(PYTEST) -m security

test-functional:
	$(PYTEST) -m functional

test-regression:
	$(PYTEST) -m regression

test-coverage:
	$(PYTEST) --cov=dealhunter --cov-report=term-missing --cov-report=xml

test-all:
	$(PYTHON) -m ruff format --check src tests
	$(PYTHON) -m ruff check src tests
	$(PYTHON) -m mypy src
	$(PYTHON) -m bandit -q -r src
	$(PYTHON) -m detect_secrets scan src
	$(PYTHON) -m pip_audit --skip-editable
	$(PYTEST) --cov=dealhunter --cov-report=term-missing --cov-report=xml

lint:
	$(PYTHON) -m ruff check src tests
	$(PYTHON) -m mypy src

format:
	$(PYTHON) -m ruff format src tests
