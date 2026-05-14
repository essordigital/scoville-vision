# scoville-vision developer Makefile
#
# Mirrors what the GitHub Actions workflow will do once the OAuth scope is
# refreshed. Run these targets locally to keep parity.

PYTHON ?= python3
VENV   ?= .venv

.PHONY: help venv install lint test scan ci build run clean

help:
	@echo "scoville-vision — developer targets"
	@echo
	@echo "  make venv      create a virtualenv in $(VENV)/"
	@echo "  make install   install package + dev deps in the venv"
	@echo "  make lint      ruff check src/"
	@echo "  make test      pytest -q (excludes integration tests)"
	@echo "  make ci        lint + test (parity with GitHub Actions)"
	@echo "  make scan      trivy image scan on the local Docker image"
	@echo "  make build     docker build -t scoville-vision:dev ."
	@echo "  make run       docker run on port 8001"
	@echo "  make clean     remove venv + caches"

venv:
	$(PYTHON) -m venv $(VENV)
	$(VENV)/bin/pip install --upgrade pip

install: venv
	$(VENV)/bin/pip install -e ".[dev]"

lint:
	$(VENV)/bin/ruff check src/

test:
	$(VENV)/bin/pytest -q

ci: lint test
	@echo "CI checks passed locally."

build:
	docker build -t scoville-vision:dev .

scan: build
	@command -v trivy >/dev/null 2>&1 || { \
	  echo "trivy not installed — see https://aquasecurity.github.io/trivy/"; \
	  exit 1; \
	}
	trivy image --severity HIGH,CRITICAL --ignore-unfixed --exit-code 1 scoville-vision:dev

run: build
	docker run --rm -p 8001:8001 \
	  -e YOLO_OFFLINE=1 \
	  --ulimit core=0 \
	  scoville-vision:dev

clean:
	rm -rf $(VENV) .pytest_cache .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
