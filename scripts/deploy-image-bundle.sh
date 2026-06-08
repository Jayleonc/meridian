#!/usr/bin/env bash
# Build Meridian Docker images locally, copy the image bundle to one server,
# load it there, and restart the runtime docker compose stack.

set -euo pipefail

cd "$(dirname "$0")/.."

TARGET="${MERIDIAN_DEPLOY_TARGET:-43.138.250.173}"
REMOTE_DIR="${MERIDIAN_DEPLOY_DIR:-/opt/meridian}"
IMAGE_PREFIX="${MERIDIAN_IMAGE_PREFIX:-meridian}"
DOCKER_PLATFORM="${MERIDIAN_DOCKER_PLATFORM:-linux/amd64}"
PYTHON_PACKAGE_INDEX_URL="${PYTHON_PACKAGE_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"
POSTGRES_IMAGE="${MERIDIAN_POSTGRES_IMAGE:-postgres:17}"
INCLUDE_POSTGRES_IMAGE="${MERIDIAN_INCLUDE_POSTGRES_IMAGE:-false}"
TAG="${MERIDIAN_IMAGE_TAG:-}"
PUBLIC_PORT="${MERIDIAN_PUBLIC_PORT:-3000}"
SSH_CONNECT_TIMEOUT="${MERIDIAN_SSH_CONNECT_TIMEOUT:-10}"
RUNTIME_ENV_SOURCE="${MERIDIAN_RUNTIME_ENV_SOURCE:-}"
RUNTIME_CONFIG_DIR_SOURCE="${MERIDIAN_RUNTIME_CONFIG_DIR_SOURCE:-}"
BUILD_IMAGES=true
DEPLOY_REMOTE=true
SMOKE_TEST=true

usage() {
    cat <<'EOF'
Usage:
  ./scripts/deploy-image-bundle.sh [options]

Options:
  --target USER@HOST       SSH/SCP target. Default: MERIDIAN_DEPLOY_TARGET or 43.138.250.173
  --remote-dir PATH        Remote runtime dir. Default: MERIDIAN_DEPLOY_DIR or /opt/meridian
  --tag TAG                Image tag. Default: git short sha or timestamp
  --image-prefix PREFIX    Image prefix. Default: meridian
  --platform PLATFORM      Docker target platform. Default: linux/amd64
  --python-index URL       Python package index used inside Docker builds
  --postgres-image IMAGE   Postgres image included in the bundle. Default: postgres:17
  --include-postgres       Include --postgres-image in docker save bundle
  --runtime-env FILE       Local .env.runtime source. If provided, remote .env.runtime is overwritten.
  --runtime-config-dir DIR Local dir with atlas/lens/probe config YAML. If provided, remote config is overwritten.
  --build-only             Build and package locally, do not scp/deploy
  --deploy-only            Reuse existing local bundle for --tag, do not rebuild
  --no-smoke               Skip final HTTP smoke test
  -h, --help               Show this help

Environment:
  MERIDIAN_DEPLOY_TARGET   Same as --target
  MERIDIAN_DEPLOY_DIR      Same as --remote-dir
  MERIDIAN_DEPLOY_URL      Public URL for smoke test, e.g. http://43.138.250.173:3000
  MERIDIAN_DOCKER_PLATFORM Same as --platform
  MERIDIAN_POSTGRES_IMAGE  Same as --postgres-image
  MERIDIAN_INCLUDE_POSTGRES_IMAGE
                            true/false. Default: false
  MERIDIAN_RUNTIME_ENV_SOURCE
                            Same as --runtime-env
  MERIDIAN_RUNTIME_CONFIG_DIR_SOURCE
                            Same as --runtime-config-dir
  MERIDIAN_SSH_CONNECT_TIMEOUT
                            SSH/SCP connection timeout seconds. Default: 10
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --target)
            TARGET="$2"
            shift 2
            ;;
        --remote-dir)
            REMOTE_DIR="$2"
            shift 2
            ;;
        --tag)
            TAG="$2"
            shift 2
            ;;
        --image-prefix)
            IMAGE_PREFIX="$2"
            shift 2
            ;;
        --platform)
            DOCKER_PLATFORM="$2"
            shift 2
            ;;
        --python-index)
            PYTHON_PACKAGE_INDEX_URL="$2"
            shift 2
            ;;
        --postgres-image)
            POSTGRES_IMAGE="$2"
            shift 2
            ;;
        --include-postgres)
            INCLUDE_POSTGRES_IMAGE=true
            shift
            ;;
        --runtime-env)
            RUNTIME_ENV_SOURCE="$2"
            shift 2
            ;;
        --runtime-config-dir)
            RUNTIME_CONFIG_DIR_SOURCE="$2"
            shift 2
            ;;
        --build-only)
            DEPLOY_REMOTE=false
            shift
            ;;
        --deploy-only)
            BUILD_IMAGES=false
            shift
            ;;
        --no-smoke)
            SMOKE_TEST=false
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            usage >&2
            exit 1
            ;;
    esac
done

if [[ -z "$TAG" ]]; then
    if git rev-parse --short HEAD >/dev/null 2>&1; then
        TAG="$(git rev-parse --short HEAD)"
    else
        TAG="$(date -u +%Y%m%d%H%M%S)"
    fi
fi

if [[ ! "$TAG" =~ ^[A-Za-z0-9._-]+$ ]]; then
    echo "Invalid tag: $TAG" >&2
    echo "Allowed characters: A-Z a-z 0-9 . _ -" >&2
    exit 1
fi

ARTIFACT_DIR=".meridian/artifacts/$TAG"
BUNDLE="$ARTIFACT_DIR/meridian-images-$TAG.tar.gz"
RELEASE_ENV="$ARTIFACT_DIR/release.env"
RUNTIME_ENV_ARTIFACT="$ARTIFACT_DIR/runtime.env"
RUNTIME_CONFIG_OVERWRITE_MARKER="$ARTIFACT_DIR/runtime-config.overwrite"
REMOTE_RELEASE_DIR="$REMOTE_DIR/releases/$TAG"

images=(
    "$IMAGE_PREFIX/nexus:$TAG"
    "$IMAGE_PREFIX/atlas:$TAG"
    "$IMAGE_PREFIX/probe:$TAG"
    "$IMAGE_PREFIX/lens:$TAG"
    "$IMAGE_PREFIX/trace:$TAG"
)

if [[ "$INCLUDE_POSTGRES_IMAGE" == "true" || "$INCLUDE_POSTGRES_IMAGE" == "1" ]]; then
    images+=("$POSTGRES_IMAGE")
fi

quote_remote() {
    printf "%q" "$1"
}

copy_runtime_inputs() {
    mkdir -p "$ARTIFACT_DIR/config"

    cp deploy/docker-compose.runtime.yml "$ARTIFACT_DIR/docker-compose.runtime.yml"
    cp deploy/runtime.env.example "$ARTIFACT_DIR/runtime.env.example"

    if [[ -n "$RUNTIME_ENV_SOURCE" ]]; then
        if [[ ! -f "$RUNTIME_ENV_SOURCE" ]]; then
            echo "Runtime env file not found: $RUNTIME_ENV_SOURCE" >&2
            exit 1
        fi
        cp "$RUNTIME_ENV_SOURCE" "$RUNTIME_ENV_ARTIFACT"
        if grep -q "<FILL_" "$RUNTIME_ENV_ARTIFACT"; then
            echo "Runtime env still contains <FILL_...> placeholders: $RUNTIME_ENV_SOURCE" >&2
            exit 1
        fi
    fi

    if [[ -n "$RUNTIME_CONFIG_DIR_SOURCE" ]]; then
        for file in atlas.config.yaml lens.config.yaml probe.config.yaml; do
            if [[ ! -f "$RUNTIME_CONFIG_DIR_SOURCE/$file" ]]; then
                echo "Runtime config file not found: $RUNTIME_CONFIG_DIR_SOURCE/$file" >&2
                exit 1
            fi
        done
        cp "$RUNTIME_CONFIG_DIR_SOURCE"/*.yaml "$ARTIFACT_DIR/config/"
        if grep -R -q "<FILL_" "$ARTIFACT_DIR/config"; then
            echo "Runtime config still contains <FILL_...> placeholders: $RUNTIME_CONFIG_DIR_SOURCE" >&2
            exit 1
        fi
        : > "$RUNTIME_CONFIG_OVERWRITE_MARKER"
    else
        cp deploy/runtime-config/*.yaml "$ARTIFACT_DIR/config/"
    fi
}

write_release_env() {
    mkdir -p "$ARTIFACT_DIR"
    cat > "$RELEASE_ENV" <<EOF
MERIDIAN_IMAGE_PREFIX=$IMAGE_PREFIX
MERIDIAN_IMAGE_TAG=$TAG
MERIDIAN_RUNTIME_ENV_FILE=.env.runtime
MERIDIAN_PUBLIC_PORT=$PUBLIC_PORT
MERIDIAN_PROBE_HOURLY_LOG_DIR=${MERIDIAN_PROBE_HOURLY_LOG_DIR:-/data/brick/log}
MERIDIAN_PROBE_SUPERVISOR_LOG_DIR=${MERIDIAN_PROBE_SUPERVISOR_LOG_DIR:-/var/log/supervisor}
MERIDIAN_PROBE_TOOLS_DIR=${MERIDIAN_PROBE_TOOLS_DIR:-/data/pinfire/tools}
EOF
}

build_images() {
    echo "==> Build Console"
    (cd console && npm run build)

    echo "==> Build Docker images: tag=$TAG prefix=$IMAGE_PREFIX platform=$DOCKER_PLATFORM"
    docker build \
        --platform "$DOCKER_PLATFORM" \
        -f deploy/docker/Dockerfile.nexus \
        --build-arg "PYTHON_PACKAGE_INDEX_URL=$PYTHON_PACKAGE_INDEX_URL" \
        -t "$IMAGE_PREFIX/nexus:$TAG" \
        .

    for svc in atlas probe lens trace; do
        docker build \
            --platform "$DOCKER_PLATFORM" \
            -f deploy/docker/Dockerfile.python-service \
            --build-arg "SERVICE=$svc" \
            --build-arg "PYTHON_PACKAGE_INDEX_URL=$PYTHON_PACKAGE_INDEX_URL" \
            -t "$IMAGE_PREFIX/$svc:$TAG" \
            .
    done

    if [[ "$INCLUDE_POSTGRES_IMAGE" == "true" || "$INCLUDE_POSTGRES_IMAGE" == "1" ]]; then
        if docker image inspect "$POSTGRES_IMAGE" >/dev/null 2>&1; then
            echo "==> Reuse local image: $POSTGRES_IMAGE"
        else
            echo "==> Pull missing image: $POSTGRES_IMAGE"
            docker pull "$POSTGRES_IMAGE"
        fi
    fi

    copy_runtime_inputs
    echo "==> Save image bundle: $BUNDLE"
    docker save "${images[@]}" | gzip -c > "$BUNDLE"
    write_release_env
}

deploy_remote() {
    if [[ ! -f "$BUNDLE" ]]; then
        echo "Missing bundle: $BUNDLE" >&2
        echo "Run without --deploy-only first, or pass the correct --tag." >&2
        exit 1
    fi

    local remote_dir_q
    local release_dir_q
    remote_dir_q="$(quote_remote "$REMOTE_DIR")"
    release_dir_q="$(quote_remote "$REMOTE_RELEASE_DIR")"

    echo "==> Prepare remote dir: $TARGET:$REMOTE_RELEASE_DIR"
    ssh -o BatchMode=yes -o ConnectTimeout="$SSH_CONNECT_TIMEOUT" "$TARGET" "mkdir -p $release_dir_q $remote_dir_q/config $remote_dir_q/logs $remote_dir_q/run"

    echo "==> SCP release artifacts"
    scp -o BatchMode=yes -o ConnectTimeout="$SSH_CONNECT_TIMEOUT" "$BUNDLE" "$ARTIFACT_DIR/docker-compose.runtime.yml" "$ARTIFACT_DIR/runtime.env.example" "$RELEASE_ENV" "$TARGET:$REMOTE_RELEASE_DIR/"
    if [[ -f "$RUNTIME_ENV_ARTIFACT" ]]; then
        scp -o BatchMode=yes -o ConnectTimeout="$SSH_CONNECT_TIMEOUT" "$RUNTIME_ENV_ARTIFACT" "$TARGET:$REMOTE_RELEASE_DIR/"
    fi
    if [[ -f "$RUNTIME_CONFIG_OVERWRITE_MARKER" ]]; then
        scp -o BatchMode=yes -o ConnectTimeout="$SSH_CONNECT_TIMEOUT" "$RUNTIME_CONFIG_OVERWRITE_MARKER" "$TARGET:$REMOTE_RELEASE_DIR/"
    fi
    scp -o BatchMode=yes -o ConnectTimeout="$SSH_CONNECT_TIMEOUT" -r "$ARTIFACT_DIR/config" "$TARGET:$REMOTE_RELEASE_DIR/"

    echo "==> Remote docker load and compose up"
    local remote_cmd
    remote_cmd=$(cat <<EOF
set -e
cd $remote_dir_q
cp releases/$TAG/docker-compose.runtime.yml docker-compose.yml
cp releases/$TAG/release.env .env.release
if [ -f releases/$TAG/runtime.env ]; then
  cp releases/$TAG/runtime.env .env.runtime
elif [ ! -f .env.runtime ]; then
  cp releases/$TAG/runtime.env.example .env.runtime
fi
for file in atlas.config.yaml lens.config.yaml probe.config.yaml; do
  if [ -f releases/$TAG/runtime-config.overwrite ]; then
    cp releases/$TAG/config/\$file config/\$file
  elif [ ! -f config/\$file ]; then
    cp releases/$TAG/config/\$file config/\$file
  fi
done
docker load -i releases/$TAG/meridian-images-$TAG.tar.gz
if docker compose version >/dev/null 2>&1; then
  docker compose --env-file .env.release -f docker-compose.yml up -d
  docker compose --env-file .env.release -f docker-compose.yml ps
else
  docker-compose --env-file .env.release -f docker-compose.yml up -d
  docker-compose --env-file .env.release -f docker-compose.yml ps
fi
EOF
)
    ssh -o BatchMode=yes -o ConnectTimeout="$SSH_CONNECT_TIMEOUT" "$TARGET" "$remote_cmd"
}

smoke_test() {
    local public_url="${MERIDIAN_DEPLOY_URL:-}"
    if [[ -z "$public_url" ]]; then
        local host="$TARGET"
        host="${host#*@}"
        host="${host%%:*}"
        public_url="http://$host:$PUBLIC_PORT"
    fi

    echo "==> Smoke test: $public_url/api/registry/status"
    curl -fsS "$public_url/api/registry/status" >/tmp/meridian-deploy-smoke.json
    python3 - <<'PY'
import json
from pathlib import Path

data = json.loads(Path("/tmp/meridian-deploy-smoke.json").read_text())
print("tool_exposure:", data.get("tool_exposure", {}).get("mode"))
print("manifest_tools:", len(data.get("manifest_tools", [])))
print("dynamic_tools_registered:", len(data.get("dynamic_tools_registered", [])))
PY
}

if [[ "$BUILD_IMAGES" == "true" ]]; then
    build_images
else
    copy_runtime_inputs
    write_release_env
fi

if [[ "$DEPLOY_REMOTE" == "true" ]]; then
    deploy_remote
    if [[ "$SMOKE_TEST" == "true" ]]; then
        smoke_test
    fi
else
    echo "Build-only completed: $BUNDLE"
fi
