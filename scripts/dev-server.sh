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
elif [[ ! -f console/dist/index.html ]]; then
    echo "错误: 已跳过 Console 构建，但 console/dist/index.html 不存在。" >&2
    echo "请在本地构建并上传前端产物：" >&2
    echo "  ./scripts/package-console-dist.sh" >&2
    echo "  scp .meridian/artifacts/console-dist.tar.gz <server>:/opt/meridian/" >&2
    echo "  ./scripts/install-console-dist.sh /opt/meridian/console-dist.tar.gz" >&2
    exit 1
fi

dev_config_path() {
    local svc="$1"
    local tracked="$PWD/deploy/dev-server/${svc}.config.yaml"
    local local_in_repo="$PWD/deploy/dev-server/${svc}.config.local.yaml"
    local local_state="$PWD/.meridian/config/${svc}.config.yaml"

    if [[ -f "$local_state" ]]; then
        printf '%s\n' "$local_state"
    elif [[ -f "$local_in_repo" ]]; then
        printf '%s\n' "$local_in_repo"
    else
        printf '%s\n' "$tracked"
    fi
}

warn_if_template_config() {
    local svc="$1"
    local path="$2"
    local tracked="$PWD/deploy/dev-server/${svc}.config.yaml"

    if [[ "$path" == "$tracked" ]]; then
        echo "⚠️  ${svc} 使用仓库模板配置；服务器真实配置请放到 .meridian/config/${svc}.config.yaml 或 deploy/dev-server/${svc}.config.local.yaml"
    fi
}

export MERIDIAN_NEXUS_HOST="${MERIDIAN_NEXUS_HOST:-0.0.0.0}"
export MERIDIAN_INTERNAL_HOST="${MERIDIAN_INTERNAL_HOST:-127.0.0.1}"
export MERIDIAN_REPO_ROOT="${MERIDIAN_REPO_ROOT:-$PWD}"
export MERIDIAN_SERVICE_LOG_DIR="${MERIDIAN_SERVICE_LOG_DIR:-$PWD/.meridian/logs}"
export MERIDIAN_RUN_DIR="${MERIDIAN_RUN_DIR:-$PWD/.meridian/run}"
export MERIDIAN_DEVOPS_ENABLED="${MERIDIAN_DEVOPS_ENABLED:-true}"
export MERIDIAN_ATLAS_CONFIG="${MERIDIAN_ATLAS_CONFIG:-$(dev_config_path atlas)}"
export MERIDIAN_PROBE_CONFIG="${MERIDIAN_PROBE_CONFIG:-$(dev_config_path probe)}"
export MERIDIAN_LENS_CONFIG="${MERIDIAN_LENS_CONFIG:-$(dev_config_path lens)}"

mkdir -p "$MERIDIAN_SERVICE_LOG_DIR" "$MERIDIAN_RUN_DIR"

args=(all)
if [[ "$INSTALL" == "true" ]]; then
    args=(--install all)
fi

echo "🌐 外部访问: http://<dev-server>:3000"
echo "🔒 内部服务: Atlas/Probe/Lens/Trace 仅绑定 ${MERIDIAN_INTERNAL_HOST}"
echo "🪵 服务日志: ${MERIDIAN_SERVICE_LOG_DIR}"
echo "🧾 Atlas 配置: ${MERIDIAN_ATLAS_CONFIG}"
echo "🧾 Probe 配置: ${MERIDIAN_PROBE_CONFIG}"
echo "🧾 Lens 配置: ${MERIDIAN_LENS_CONFIG}"
warn_if_template_config atlas "$MERIDIAN_ATLAS_CONFIG"
warn_if_template_config probe "$MERIDIAN_PROBE_CONFIG"
warn_if_template_config lens "$MERIDIAN_LENS_CONFIG"
echo "🧰 DevOps MCP: enabled via Nexus /mcp/stream/"
exec ./scripts/dev.sh "${args[@]}"
