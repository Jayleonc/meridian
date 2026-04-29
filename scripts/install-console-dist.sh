#!/usr/bin/env bash
# Install a prebuilt Console dist archive on a development server.

set -euo pipefail
cd "$(dirname "$0")/.."

ARCHIVE="${1:-}"

if [[ -z "$ARCHIVE" ]]; then
    echo "用法: ./scripts/install-console-dist.sh <console-dist.tar.gz>" >&2
    exit 1
fi

if [[ ! -f "$ARCHIVE" ]]; then
    echo "错误: 找不到归档文件 $ARCHIVE" >&2
    exit 1
fi

rm -rf console/dist
tar -C console -xzf "$ARCHIVE"

if [[ ! -f console/dist/index.html ]]; then
    echo "错误: 归档文件中没有 console/dist/index.html" >&2
    exit 1
fi

echo "✅ Console dist 已安装到 console/dist"
