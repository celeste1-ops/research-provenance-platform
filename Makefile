# Research provenance tool — one-command entry points (PRD §13).
UV      ?= uv
PY      := $(UV) run --extra ots python
PORT    ?= 8765

.PHONY: help install dev run test test-network lint fmt web demo verify-py freetsa-certs clean

help:
	@echo "make install      install Python (uv) and web (npm) dependencies"
	@echo "make dev          backend with reload on 127.0.0.1:$(PORT) + Vite dev server on 127.0.0.1:5173"
	@echo "make run          build the UI and serve everything on 127.0.0.1:$(PORT)"
	@echo "make test         ruff + full pytest suite (network tests skipped)"
	@echo "make test-network run the tests that need real FreeTSA / OpenTimestamps"
	@echo "make demo         load the FSF sample data into the data directory"
	@echo "make verify-py    regenerate dist/verify.py from the core library"

install:
	$(UV) sync --extra ots
	cd web && npm ci

web/node_modules:
	cd web && npm ci

web: web/node_modules
	cd web && npm run build

dev: web/node_modules
	RPROV_DEV=1 $(PY) -m app --port $(PORT) --reload & \
	cd web && RPROV_PORT=$(PORT) npm run dev

run: web
	$(PY) -m app --port $(PORT)

lint:
	$(UV) run ruff check .

fmt:
	$(UV) run ruff format .

test: lint
	$(UV) run --extra ots pytest

test-network:
	RPROV_NETWORK_TESTS=1 $(UV) run --extra ots pytest -m network

demo:
	$(PY) -m app.demo

verify-py:
	$(PY) tools/build_verify.py --out dist/verify.py

freetsa-certs:
	$(PY) tools/update_freetsa_certs.py

clean:
	rm -rf dist web/dist .pytest_cache
