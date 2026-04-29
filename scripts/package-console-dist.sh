#!/usr/bin/env bash
# Build Console locally and package console/dist for a server that cannot run Node.

set -euo pipefail
cd "$(dirname "$0")/.."

BUILD=true
OUTPUT="${1:-.meridian/artifacts/console-dist.tar.gz}"

if [[ "${1:-}" == "--skip-build" ]]; then
    BUILD=false
    OUTPUT="${2:-.meridian/artifacts/console-dist.tar.gz}"
fi

if [[ "$BUILD" == "true" ]]; then
    echo "🏗️  构建 Console 静态资源..."
    (cd console && npm install && npm run build)
fi

if [[ ! -f console/dist/index.html ]]; then
    echo "错误: console/dist/index.html 不存在。请先在有 Node >= 20 的机器上构建 Console。" >&2
    exit 1
fi

mkdir -p "$(dirname "$OUTPUT")"
tar -C console -czf "$OUTPUT" dist

echo "✅ Console dist 已打包: $OUTPUT"
