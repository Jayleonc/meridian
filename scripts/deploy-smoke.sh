#!/usr/bin/env bash
# Smoke test a deployed Nexus endpoint, authenticating first when demo auth is enabled.

set -euo pipefail

cd "$(dirname "$0")/.."

PUBLIC_URL="${MERIDIAN_DEPLOY_URL:-http://43.138.250.173:3000}"
RUNTIME_ENV="${MERIDIAN_RUNTIME_ENV:-}"
COOKIE_JAR="$(mktemp)"
RESPONSE_FILE="$(mktemp)"

cleanup() {
    rm -f "$COOKIE_JAR" "$RESPONSE_FILE"
}
trap cleanup EXIT

read_env_file_value() {
    local key="$1"
    local file="${2:-}"
    if [[ -z "$file" || ! -f "$file" ]]; then
        return 0
    fi
    awk -F= -v key="$key" '
        $1 == key {
            sub(/^[^=]*=/, "")
            sub(/\r$/, "")
            print
            exit
        }
    ' "$file"
}

env_value() {
    local key="$1"
    local value="${!key:-}"
    if [[ -n "$value" ]]; then
        printf "%s" "$value"
        return 0
    fi
    read_env_file_value "$key" "$RUNTIME_ENV"
}

is_true() {
    case "$(printf "%s" "$1" | tr '[:upper:]' '[:lower:]')" in
        1|true|yes|on) return 0 ;;
        *) return 1 ;;
    esac
}

json_login_body() {
    AUTH_USER="$1" AUTH_PASSWORD="$2" python3 - <<'PY'
import json
import os

print(json.dumps({
    "username": os.environ["AUTH_USER"],
    "password": os.environ["AUTH_PASSWORD"],
}))
PY
}

public_url="${PUBLIC_URL%/}"
auth_enabled="$(env_value NEXUS_AUTH_ENABLED)"
demo_enabled="$(env_value NEXUS_DEMO_MODE)"

if is_true "$auth_enabled"; then
    auth_user="$(env_value NEXUS_AUTH_USERNAME)"
    auth_password="$(env_value NEXUS_AUTH_PASSWORD)"
    if [[ -z "$auth_user" || -z "$auth_password" ]]; then
        echo "Nexus auth is enabled, but NEXUS_AUTH_USERNAME or NEXUS_AUTH_PASSWORD is missing." >&2
        exit 1
    fi

    echo "==> Smoke auth login: $public_url/api/auth/login"
    curl -fsS \
        -c "$COOKIE_JAR" \
        -H "Content-Type: application/json" \
        -d "$(json_login_body "$auth_user" "$auth_password")" \
        "$public_url/api/auth/login" \
        >/dev/null
    curl_args=(-b "$COOKIE_JAR")
else
    curl_args=()
fi

if is_true "$demo_enabled"; then
    smoke_path="/api/nexus"
    echo "==> Smoke nexus: $public_url$smoke_path"
else
    smoke_path="/api/registry/status"
    echo "==> Smoke registry: $public_url$smoke_path"
fi
curl -fsS "${curl_args[@]}" "$public_url$smoke_path" >"$RESPONSE_FILE"

python3 - "$RESPONSE_FILE" <<'PY'
import json
import sys
from pathlib import Path

data = json.loads(Path(sys.argv[1]).read_text())
if "demo" in data:
    print("name:", data.get("name"))
    print("demo_enabled:", data.get("demo", {}).get("enabled"))
    print("auth_enabled:", data.get("auth", {}).get("enabled"))
else:
    print("tool_exposure:", data.get("tool_exposure", {}).get("mode"))
    print("manifest_tools:", len(data.get("manifest_tools", [])))
    print("dynamic_tools_registered:", len(data.get("dynamic_tools_registered", [])))
PY
