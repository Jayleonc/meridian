.PHONY: help install start stop restart clean nexus atlas probe lens deploy deploy-build deploy-existing deploy-smoke

MERIDIAN_DEPLOY_TARGET ?= hldev
MERIDIAN_DEPLOY_URL ?= http://43.138.250.173:3000
MERIDIAN_RUNTIME_ENV ?= .meridian/deploy/highlink/.env.runtime
MERIDIAN_RUNTIME_CONFIG_DIR ?= .meridian/deploy/highlink/config
MERIDIAN_DOCKER_PLATFORM ?= linux/amd64

# 默认目标
help:
	@echo "Meridian"
	@echo ""
	@echo "Available commands:"
	@echo ""
	@echo "Local development:"
	@echo "  install     Install dependencies for all services"
	@echo "  start       Start backend services locally"
	@echo "  stop        Stop all services"
	@echo "  restart     Restart all services"
	@echo "  nexus       Start Nexus gateway (port 3000)"
	@echo "  atlas       Start Atlas service (port 3001)"
	@echo "  probe       Start Probe service (port 3002)"
	@echo "  lens        Start Lens service (port 3003)"
	@echo ""
	@echo "Image bundle deployment:"
	@echo "  deploy      Build images, scp bundle, docker-compose up on $(MERIDIAN_DEPLOY_TARGET)"
	@echo "  deploy-build"
	@echo "              Build local image bundle only"
	@echo "  deploy-existing TAG=<tag>"
	@echo "              Deploy an existing .meridian/artifacts/<tag> bundle"
	@echo "  deploy-smoke"
	@echo "              Check deployed Nexus registry status"
	@echo ""
	@echo "Maintenance:"
	@echo "  clean       Clean Python cache and build files"
	@echo ""
	@echo "Deploy defaults:"
	@echo "  target      $(MERIDIAN_DEPLOY_TARGET)"
	@echo "  url         $(MERIDIAN_DEPLOY_URL)"
	@echo "  runtime env $(MERIDIAN_RUNTIME_ENV)"
	@echo "  config dir  $(MERIDIAN_RUNTIME_CONFIG_DIR)"
	@echo "  platform    $(MERIDIAN_DOCKER_PLATFORM)"

# 安装依赖
install:
	@echo "Installing dependencies..."
	cd nexus && uv sync
	cd atlas && uv sync
	cd probe && uv sync
	cd lens && uv sync

# 启动所有服务
start:
	@echo "Starting all Meridian services..."
	@echo "Nexus: http://localhost:3000"
	@echo "Atlas: http://localhost:3001"
	@echo "Probe: http://localhost:3002"
	@echo "Lens:  http://localhost:3003"
	@echo ""
	@echo "Press Ctrl+C to stop all services"
	@echo ""
	@trap 'kill 0' SIGINT; \
	(cd nexus && uv run uvicorn src.server:app --host 0.0.0.0 --port 3000 --reload --no-access-log &) && \
	(cd atlas && uv run uvicorn app.main:app --host 0.0.0.0 --port 3001 --reload --no-access-log &) && \
	(cd probe && uv run uvicorn app.main:app --host 0.0.0.0 --port 3002 --reload --no-access-log &) && \
	(cd lens && uv run uvicorn app.main:app --host 0.0.0.0 --port 3003 --reload --no-access-log &) && \
	wait

# 启动单个服务
nexus:
	@echo "Starting Nexus gateway on port 3000..."
	cd nexus && uv run uvicorn src.server:app --host 0.0.0.0 --port 3000 --reload --no-access-log

atlas:
	@echo "Starting Atlas service on port 3001..."
	cd atlas && uv run uvicorn app.main:app --host 0.0.0.0 --port 3001 --reload --no-access-log

probe:
	@echo "Starting Probe service on port 3002..."
	cd probe && uv run uvicorn app.main:app --host 0.0.0.0 --port 3002 --reload --no-access-log

lens:
	@echo "Starting Lens service on port 3003..."
	cd lens && uv run uvicorn app.main:app --host 0.0.0.0 --port 3003 --reload --no-access-log

deploy:
	MERIDIAN_DEPLOY_URL="$(MERIDIAN_DEPLOY_URL)" ./scripts/deploy-image-bundle.sh \
		--target "$(MERIDIAN_DEPLOY_TARGET)" \
		--platform "$(MERIDIAN_DOCKER_PLATFORM)" \
		--runtime-env "$(MERIDIAN_RUNTIME_ENV)" \
		--runtime-config-dir "$(MERIDIAN_RUNTIME_CONFIG_DIR)"

deploy-build:
	./scripts/deploy-image-bundle.sh \
		--build-only \
		--platform "$(MERIDIAN_DOCKER_PLATFORM)" \
		--runtime-env "$(MERIDIAN_RUNTIME_ENV)" \
		--runtime-config-dir "$(MERIDIAN_RUNTIME_CONFIG_DIR)"

deploy-existing:
	@if [ -z "$(TAG)" ]; then \
		echo "Usage: make deploy-existing TAG=<artifact-tag>"; \
		exit 1; \
	fi
	MERIDIAN_DEPLOY_URL="$(MERIDIAN_DEPLOY_URL)" ./scripts/deploy-image-bundle.sh \
		--deploy-only \
		--tag "$(TAG)" \
		--target "$(MERIDIAN_DEPLOY_TARGET)" \
		--runtime-env "$(MERIDIAN_RUNTIME_ENV)" \
		--runtime-config-dir "$(MERIDIAN_RUNTIME_CONFIG_DIR)"

deploy-smoke:
	MERIDIAN_DEPLOY_URL="$(MERIDIAN_DEPLOY_URL)" MERIDIAN_RUNTIME_ENV="$(MERIDIAN_RUNTIME_ENV)" bash scripts/deploy-smoke.sh

# 停止服务
stop:
	@echo "Stopping all services..."
	pkill -f "uvicorn app.main:app" || true
	pkill -f "uvicorn src.server:app" || true

# 重启服务
restart: stop start

# 清理
clean:
	@echo "Cleaning up..."
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
