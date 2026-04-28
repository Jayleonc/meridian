#!/usr/bin/env bash
# 用 uv 直接启动单个服务（不依赖 Docker Compose）
#
# 用法:
#   ./scripts/dev.sh all            # 启动所有后端服务
#   ./scripts/dev.sh atlas          # 启动 Atlas (port 3001)
#   ./scripts/dev.sh probe          # 启动 Probe (port 3002)
#   ./scripts/dev.sh nexus          # 启动 Nexus (port 3000)
#   ./scripts/dev.sh atlas probe    # 同时启动多个（后台）
#   ./scripts/dev.sh --install atlas # 先安装依赖再启动

set -euo pipefail
cd "$(dirname "$0")/.."

if [[ -f .env ]]; then
    set -a
    source .env
    set +a
fi

INSTALL=false
if [[ "${1:-}" == "--install" ]]; then
    INSTALL=true
    shift
fi

ALL_SERVICES=(atlas probe lens trace nexus)

if [[ $# -eq 0 ]]; then
    SERVICES=(atlas)
elif [[ "${1:-}" == "all" ]]; then
    SERVICES=("${ALL_SERVICES[@]}")
else
    SERVICES=("$@")
fi

write_service_state() {
    local svc="$1"
    local host="$2"
    local port="$3"
    local app_path="$4"
    local log_file="${5:-}"

    if [[ -z "${MERIDIAN_RUN_DIR:-}" ]]; then
        return
    fi

    mkdir -p "$MERIDIAN_RUN_DIR"
    local state_file="$MERIDIAN_RUN_DIR/$svc.json"
    local started_at
    started_at="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
    printf '{\n' > "$state_file"
    printf '  "service": "%s",\n' "$svc" >> "$state_file"
    printf '  "host": "%s",\n' "$host" >> "$state_file"
    printf '  "port": %s,\n' "$port" >> "$state_file"
    printf '  "app_path": "%s",\n' "$app_path" >> "$state_file"
    printf '  "wrapper_pid": %s,\n' "$BASHPID" >> "$state_file"
    printf '  "started_at": "%s",\n' "$started_at" >> "$state_file"
    printf '  "log_file": "%s"\n' "$log_file" >> "$state_file"
    printf '}\n' >> "$state_file"
}

start_service() {
    local svc="$1"
    local dir="$PWD/$svc"

    if [[ ! -d "$dir" ]]; then
        echo "错误: 服务目录不存在 $dir" >&2
        return 1
    fi

    if [[ "$INSTALL" == "true" ]]; then
        echo "📦 安装 $svc 依赖..."
        (cd "$dir" && uv sync)
    fi

    # 从 config.yaml 读取端口，fallback 到默认值
    local port
    local app_path="app.main:app"
    case "$svc" in
        nexus)  port=3000; app_path="src.server:app" ;;
        atlas)  port=3001 ;;
        probe)  port=3002 ;;
        lens)   port=3003 ;;
        trace)  port=3004; app_path="src.server:app" ;;
        *)      echo "错误: 未知服务 $svc" >&2; return 1 ;;
    esac

    local access_log="${MERIDIAN_UVICORN_ACCESS_LOG:-false}"
    local access_log_args=()
    if [[ "$access_log" != "true" && "$access_log" != "1" ]]; then
        access_log_args+=(--no-access-log)
    fi

    local host
    if [[ "$svc" == "nexus" ]]; then
        host="${MERIDIAN_NEXUS_HOST:-0.0.0.0}"
    else
        host="${MERIDIAN_INTERNAL_HOST:-0.0.0.0}"
    fi

    echo "🚀 启动 $svc ($host:$port)..."
    local log_file=""
    if [[ -n "${MERIDIAN_SERVICE_LOG_DIR:-}" ]]; then
        mkdir -p "$MERIDIAN_SERVICE_LOG_DIR"
        log_file="$MERIDIAN_SERVICE_LOG_DIR/$svc.log"
        printf '\n[%s] starting %s on %s:%s\n' "$(date -u +"%Y-%m-%dT%H:%M:%SZ")" "$svc" "$host" "$port" >> "$log_file"
    fi
    write_service_state "$svc" "$host" "$port" "$app_path" "$log_file"

    if [[ -n "$log_file" ]]; then
        (cd "$dir" && uv run uvicorn "$app_path" --reload --host "$host" --port "$port" "${access_log_args[@]}") 2>&1 | tee -a "$log_file"
    else
        (cd "$dir" && uv run uvicorn "$app_path" --reload --host "$host" --port "$port" "${access_log_args[@]}")
    fi
}

if [[ ${#SERVICES[@]} -eq 1 ]]; then
    # 单服务：前台运行
    start_service "${SERVICES[0]}"
else
    # 多服务：后台运行，Ctrl+C 全部停止
    PIDS=()
    for svc in "${SERVICES[@]}"; do
        start_service "$svc" &
        PIDS+=($!)
    done

    trap 'echo "🛑 停止所有服务..."; kill "${PIDS[@]}" 2>/dev/null; wait' INT TERM
    echo "💡 按 Ctrl+C 停止所有服务"
    wait
fi
