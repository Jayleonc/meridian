#!/usr/bin/env bash
# Start Meridian on a development server without Docker.
#
# Only Nexus binds to an external interface. Atlas/Probe/Lens/Trace stay on
# loopback and are reached through Nexus routes on port 3000.

set -euo pipefail
cd "$(dirname "$0")/.."

INSTALL=false
BUILD_CONSOLE=true

while [[ $# -gt 0 ]]; do
    case "$1" in
        --install)
            INSTALL=true
            shift
            ;;
        --skip-console-build)
            BUILD_CONSOLE=false
            shift
            ;;
        *)
            echo "未知参数: $1" >&2
            echo "用法: ./scripts/dev-server.sh [--install] [--skip-console-build]" >&2
            exit 1
            ;;
    esac
done

if [[ "$BUILD_CONSOLE" == "true" ]]; then
    if [[ "$INSTALL" == "true" ]]; then
        echo "📦 安装 Console 依赖..."
        (cd console && npm install)
    fi

    echo "🏗️  构建 Console 静态资源..."
    (cd console && npm run build)
fi

export MERIDIAN_NEXUS_HOST="${MERIDIAN_NEXUS_HOST:-0.0.0.0}"
export MERIDIAN_INTERNAL_HOST="${MERIDIAN_INTERNAL_HOST:-127.0.0.1}"
export MERIDIAN_REPO_ROOT="${MERIDIAN_REPO_ROOT:-$PWD}"
export MERIDIAN_SERVICE_LOG_DIR="${MERIDIAN_SERVICE_LOG_DIR:-$PWD/.meridian/logs}"
export MERIDIAN_RUN_DIR="${MERIDIAN_RUN_DIR:-$PWD/.meridian/run}"
export MERIDIAN_DEVOPS_ENABLED="${MERIDIAN_DEVOPS_ENABLED:-true}"

mkdir -p "$MERIDIAN_SERVICE_LOG_DIR" "$MERIDIAN_RUN_DIR"

args=(all)
if [[ "$INSTALL" == "true" ]]; then
    args=(--install all)
fi

echo "🌐 外部访问: http://<dev-server>:3000"
echo "🔒 内部服务: Atlas/Probe/Lens/Trace 仅绑定 ${MERIDIAN_INTERNAL_HOST}"
echo "🪵 服务日志: ${MERIDIAN_SERVICE_LOG_DIR}"
echo "🧰 DevOps MCP: enabled via Nexus /mcp/stream/"
exec ./scripts/dev.sh "${args[@]}"
