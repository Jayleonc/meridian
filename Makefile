.PHONY: help install start stop restart clean nexus atlas probe lens package-console-dist install-console-dist dev-server-prebuilt

# 默认目标
help:
	@echo "Meridian Backend Services"
	@echo ""
	@echo "Available commands:"
	@echo "  install     Install dependencies for all services"
	@echo "  start       Start all services (Nexus:3000, Atlas:3001, Probe:3002, Lens:3003)"
	@echo "  stop        Stop all services"
	@echo "  restart     Restart all services"
	@echo "  nexus       Start Nexus gateway (port 3000)"
	@echo "  atlas       Start Atlas service (port 3001)"
	@echo "  probe       Start Probe service (port 3002)"
	@echo "  lens        Start Lens service (port 3003)"
	@echo "  package-console-dist  Build and package Console to deploy/console-dist.tar.gz"
	@echo "  dev-server-prebuilt   Install deploy/console-dist.tar.gz and start dev server without Node build"
	@echo "  clean       Clean up Python cache and build files"

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

# 构建并打包 Console 静态产物，供开发服务器直接安装
package-console-dist:
	./scripts/package-console-dist.sh deploy/console-dist.tar.gz

# 安装仓库内预构建 Console 静态产物
install-console-dist:
	./scripts/install-console-dist.sh deploy/console-dist.tar.gz

# 开发服务器拉取代码后可直接使用预构建产物启动，避免服务器 Node 版本或构建依赖阻塞
dev-server-prebuilt: install-console-dist
	./scripts/dev-server.sh --skip-console-build

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
