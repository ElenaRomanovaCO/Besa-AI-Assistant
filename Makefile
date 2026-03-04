# =============================================================================
# BeSa AI Assistant — Project Makefile
# =============================================================================
# Usage:
#   make layer        Build Lambda dependency layer (Docker, recommended)
#   make layer-local  Build Lambda dependency layer (local pip, Linux only)
#   make test         Run unit tests
#   make test-all     Run unit + integration tests with coverage
#   make lint         Run flake8 + mypy
#   make deploy       Deploy all CDK stacks
#   make destroy      Tear down all CDK stacks
# =============================================================================

.PHONY: layer layer-local test test-all lint deploy destroy clean

# --------------------------------------------------------------------------- #
# Lambda Layer
# --------------------------------------------------------------------------- #

layer:
	@echo "Building Lambda layer (Docker)..."
	bash backend/scripts/build_layer.sh

layer-local:
	@echo "Building Lambda layer (local pip)..."
	bash backend/scripts/build_layer.sh --local

# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #

test:
	cd backend && python -m pytest tests/unit/ -v --tb=short

test-all:
	cd backend && python -m pytest tests/ -v --tb=short \
		--cov=backend --cov-report=term-missing --cov-report=html

lint:
	cd backend && python -m flake8 agents/ handlers/ models/ services/ --max-line-length=100
	cd backend && python -m mypy agents/ handlers/ models/ services/ --ignore-missing-imports

# --------------------------------------------------------------------------- #
# CDK
# --------------------------------------------------------------------------- #

deploy: layer
	@echo "Deploying all CDK stacks..."
	cd infrastructure && cdk deploy --all --require-approval never

destroy:
	@echo "Destroying all CDK stacks..."
	cd infrastructure && cdk destroy --all

# --------------------------------------------------------------------------- #
# Frontend
# --------------------------------------------------------------------------- #

frontend-install:
	cd frontend && npm install

frontend-dev:
	cd frontend && npm run dev

frontend-build:
	cd frontend && npm run build

# --------------------------------------------------------------------------- #
# Cleanup
# --------------------------------------------------------------------------- #

clean:
	rm -rf backend/layer/python/
	rm -rf backend/.pytest_cache backend/htmlcov backend/.coverage
	find . -name "*.pyc" -delete
	find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
