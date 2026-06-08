# Meridian

MCP（Model Context Protocol）驱动的智能运维观测平台。

长期工程边界和不可变原则见 [`constitution.md`](constitution.md)。当 README、spec、plan 与宪法冲突时，以宪法为准。

## 项目结构

| 模块 | 职责 |
|------|------|
| **atlas** | Meta MCP 服务 — 元数据管理与服务注册 |
| **probe** | 日志观测 MCP — 日志采集、搜索与分析 |
| **lens** | 数据查询 MCP — DSL 风控规则引擎 |
| **trace** | 链路关联 MCP — 分布式追踪与链路分析 |
| **nexus** | MCP 网关 — 统一入口、受控工具面与服务代理 |
| **forge** | MCP Builder — MCP 服务构建工具 |
| **codex** | 诊断知识库 — 故障模式与解决方案 |
| **console** | React 前端 — 可视化控制台与 Agent 交互入口 |
| **shared** | 共享代码 — 数据模型、MCP SDK、数据库工具 |

## 快速开始

```bash
# 启动本地开发环境
./scripts/dev-up.sh

# 或者直接启动所有后端服务（Nexus/Atlas/Probe/Lens/Trace）
./scripts/dev.sh all

# 部署到开发服务器
./scripts/dev-server.sh
```

## 端口约定

开发服务器只暴露 `3000`，由 **Nexus** 作为唯一入口。其他服务使用内部端口：

| 服务 | 端口 |
|------|------|
| Nexus | 3000 |
| Atlas | 3001 |
| Probe | 3002 |
| Lens | 3003 |
| Trace | 3004 |

## 开发服务器镜像包部署

如果开发服务器有 Docker / Docker Compose，但不希望放源码，推荐使用镜像包发布链路。源码只在本地或构建机，服务器只接收 Docker images、runtime compose 和配置模板。

```bash
# 默认目标是 hldev，默认运行目录是 /opt/meridian
make deploy

# 只在本地构建镜像包，不 scp / 不部署；会校验本地 runtime 配置
make deploy-build

# 复用已经构建好的镜像包
make deploy-existing TAG=codex-smoke

# 冒烟检查
make deploy-smoke
```

发布脚本会执行：

```text
npm run build
docker build meridian/{nexus,atlas,probe,lens,trace}:<tag>
docker save ... > .meridian/artifacts/<tag>/meridian-images-<tag>.tar.gz
scp 到 /opt/meridian/releases/<tag>
远端 docker load
远端 docker compose up -d
curl /api/registry/status 冒烟检查
```

构建会复用 Docker layer cache 和 BuildKit uv cache：业务代码改动不会重新下载 Python 依赖；只有 `pyproject.toml` / `uv.lock` 改动时才会重新同步依赖，并且会复用本机 uv 下载缓存。Python 包索引默认使用清华 PyPI mirror，可通过 `--python-index <url>` 覆盖。开发服务器是 x86_64，Makefile 默认强制构建 `linux/amd64` 镜像，避免 Apple Silicon 本机产出 arm64 镜像导致服务器 `exec format error`。

runtime compose 默认复用开发服务器宿主机已有的 Meridian PostgreSQL，例如 `127.0.0.1:15432` 上的 `meridian-postgres`。容器内通过 `host.docker.internal:15432` 访问它；不会再额外启动一个空的 PostgreSQL 服务。

服务器运行目录只需要保留：

```text
/opt/meridian/
  docker-compose.yml
  .env.release        # 当前镜像 tag，由脚本更新
  .env.runtime        # 运行配置，首次发布自动生成，后续不覆盖
  config/             # atlas/probe/lens runtime yaml，首次发布自动生成，后续不覆盖
  logs/
  run/
  releases/
```

## 开发服务器直跑

如果不使用 Docker，可以在开发服务器直接克隆仓库后启动：

```bash
cp .env.example .env
# 按需填写 OPENAI_API_KEY / MERIDIAN_MODEL_BASE_URL 等模型配置

./scripts/dev-server.sh --install
```

`dev-server.sh` 会先构建 `console/dist`，然后让 Nexus 监听 `0.0.0.0:3000`，Atlas / Probe / Lens / Trace 默认只监听 `127.0.0.1:3001-3004`。外部访问只需要：

```text
http://<dev-server>:3000
```

Console 静态资源由 Nexus 托管，Console 的所有后端请求仍走 `/api/*`、`/svc/*`、`/api/chat/*`、`/mcp/*`，不需要额外开放 `3010`。Probe 页面支持按服务查看日志：从服务列表、Trace 服务节点或 Atlas 服务表点击服务名，会跳到 `/probe?tab=service&svc=<service>` 并直接读取该服务最近日志；从日志行点击“追踪”时会携带该行日志时间，自动换算 request_id 查询需要的 `glog.sh -b` 回看小时数。

Nexus 是统一入口，但不是下游 MCP 的透明代理。它对外暴露的是 Nexus 命名、约束和审计后的工具面；Atlas / Probe / Lens 的内部 MCP 工具不会因为接入 Nexus 就自动全量对外可见。`/registry` 会返回当前受控暴露策略和 Nexus allowlist 中的工具列表。

Nexus 默认从 `nexus/src/registry_manifests/default.json` 加载服务和工具 manifest；需要验证外部 manifest 时可设置 `NEXUS_REGISTRY_MANIFEST=/path/to/registry.json`。已批准且可由通用 adapter 覆盖的 manifest 工具会在启动时动态注册为 Nexus MCP tool。当前 Atlas / Lens 的普通工具已走这条动态路径，Probe 仍保留手写 wrapper 作为兼容入口。

Nexus 的动态工具会进入统一 gateway pipeline：状态/权限检查、HTTP adapter 调用、超时隔离、结构化错误、响应裁剪、敏感字段脱敏和 JSONL 审计。`/api/registry/status` 可查看当前动态注册工具、manifest 工具清单和 reload 策略。FastMCP 当前可安全追加新工具名；替换已有工具定义仍建议重启 Nexus。

Console 已提供 `/nexus` 只读页面，用于查看 Nexus registry、动态 MCP 工具、manifest 状态、权限 scope、risk、adapter、输入 schema、审批元数据和 reload 策略。

如果开发服务器没有 PostgreSQL，可以只用 Docker 启动 Meridian 平台库，不需要重启 Docker daemon：

```bash
docker-compose -f docker-compose.pg.yml up -d
docker-compose -f docker-compose.pg.yml ps
```

这个 compose 会在本机开放 `127.0.0.1:15432`，并使用当前 Atlas / Lens 配置：

```text
database: meridian
user: root
password: jayleonc
```

业务 MySQL 按只读边界接入：Atlas 只查询 `information_schema` 采集表结构，Lens 的 MySQL adapter 会拒绝非 `SELECT`、多语句、没有 `LIMIT` 或包含写入/管理类关键字的 SQL。开发环境即使暂时拿到读写账号，应用层也不应执行写入；正式或长期开发环境仍建议给 Meridian 单独创建只授予 `SELECT` 的数据库账号。

开发服务器使用独立配置文件，不和模块本地 `settings/config.yaml` 混用。仓库内的默认配置是模板兜底：

```text
deploy/dev-server/atlas.config.yaml
deploy/dev-server/probe.config.yaml
deploy/dev-server/lens.config.yaml
```

服务器真实数据库账号、密码和日志路径不要直接改 tracked 的 `deploy/dev-server/*.config.yaml`，否则 `git pull` 可能覆盖。`dev-server.sh` 会按下面顺序选择配置：

```text
.meridian/config/{atlas,probe,lens}.config.yaml
deploy/dev-server/{atlas,probe,lens}.config.local.yaml
deploy/dev-server/{atlas,probe,lens}.config.yaml
```

推荐在服务器上把真实配置放到 `.meridian/config/`：

```bash
mkdir -p .meridian/config
cp deploy/dev-server/lens.config.yaml .meridian/config/lens.config.yaml
cp deploy/dev-server/atlas.config.yaml .meridian/config/atlas.config.yaml
cp deploy/dev-server/probe.config.yaml .meridian/config/probe.config.yaml
# 然后只编辑 .meridian/config/*.config.yaml 中的真实账号、密码和路径
```

也可以显式设置 `MERIDIAN_ATLAS_CONFIG`、`MERIDIAN_PROBE_CONFIG`、`MERIDIAN_LENS_CONFIG` 指向任意外部路径。Probe 默认按 `Asia/Shanghai` 业务日志时区查找 `/data/brick/log/YYYYMMDDHH.log` 小时文件；如果服务器日志文件名使用其他时区，修改本地覆盖配置的 `time.log_timezone`。Atlas 在开发服务器配置中不会每次启动都重新全量采集业务 MySQL，而是优先从 Meridian PostgreSQL 恢复最近一次 schema 快照；需要重新采集时再通过 Console / API / MCP 手动 refresh。

启动时如果看到 `使用仓库模板配置` 警告，说明当前服务没有命中本地覆盖配置；生产或共享服务器上应先补 `.meridian/config/*.config.yaml`。例如 MySQL 日志里出现 `using password: NO`，通常就是 Lens 读到了模板里的空密码配置。

启动后，`dev-server.sh` 会把各服务输出写入：

```text
.meridian/logs/nexus.log
.meridian/logs/atlas.log
.meridian/logs/probe.log
.meridian/logs/lens.log
.meridian/logs/trace.log
```

Nexus 同时暴露只读 DevOps MCP 工具，方便开发者本地连接开发服务器观察 Meridian 自身：

```bash
python3 scripts/agent_cli.py --nexus-url http://<dev-server>:3000 --once /devops
python3 scripts/agent_cli.py --nexus-url http://<dev-server>:3000 --once "/logs nexus 120"
python3 scripts/agent_cli.py --nexus-url http://<dev-server>:3000 --once /smoke
```

对应 MCP tools：

```text
devops.runtime_status
devops.list_service_logs
devops.tail_service_log
devops.config_check
devops.smoke_test
devops.console_status
```

这些工具默认只读：查看健康状态、配置缺口、Console 构建状态和服务日志，不执行重启、改配置或写业务数据。

## 本地验证 Nexus -> Probe

启动最小链路：

```bash
./scripts/dev.sh probe nexus
```

打开交互式 Agent CLI：

```bash
python3 scripts/agent_cli.py
```

常用命令：

```text
/tools
/services
/errors
/search timeout
/trace <request_id>
```

这条链路不依赖外部大模型，CLI 会通过 `http://127.0.0.1:3000/mcp/stream/` 调 Nexus，再由 Nexus 调用自己显式暴露的 `probe.*` 工具并转发到 Probe HTTP API。

Console 本地开发同样经由 Nexus 转发后端请求，不再直接连接 Atlas / Probe / Lens。

## Agent Chat

Console 的 `Agent` 页面调用 Nexus 的 `/api/chat/*`。这套接口是 Meridian 自己的会话协议，不绑定 OpenAI Responses / Agents SDK。页面左侧会列出最近会话，支持从历史会话继续排障；刷新后优先恢复最近一次打开的会话。

首期模型层通过 LangChain 适配：

复制 `.env.example` 到 `.env`，填入真实 key：

```env
MERIDIAN_MODEL_PROVIDER=openai
MERIDIAN_MODEL_NAME=gpt-4.1
OPENAI_API_KEY=...
```

如果要接 OpenAI-compatible 网关或本地模型服务：

```env
MERIDIAN_MODEL_PROVIDER=openai-compatible
MERIDIAN_MODEL_NAME=<model-name>
MERIDIAN_MODEL_BASE_URL=http://127.0.0.1:<port>/v1
MERIDIAN_MODEL_API_KEY=<api-key-or-placeholder>
```

启动 Nexus 与 Console 后访问 `/chat`。Agent 当前可通过 Nexus 调用 Probe 的日志搜索、错误巡检、request_id 追踪、服务列表和日志上下文工具。
Console 会把当前 Agent 会话 ID 保存在浏览器本地，并通过 Meridian PostgreSQL 持久化 `chat_session` / `chat_message`；刷新页面后会恢复最近一次会话。PostgreSQL 不可用时 Nexus 会自动降级为进程内存会话，服务仍可用但刷新或重启后不会恢复历史消息。
开发者排查 Agent 卡住、重复返回或工具调用异常时，可以通过 DevOps MCP 只读回看会话：`devops.list_chat_sessions`、`devops.search_chat_messages`、`devops.get_chat_session`；对应 HTTP 入口为 `/api/devops/chat/sessions`、`/api/devops/chat/search`、`/api/devops/chat/sessions/{session_id}`。

Agent 单轮请求默认最多等待 60 秒，单次模型请求默认最多等待 45 秒，避免模型网关或网络问题让 Console 一直停在 Thinking：

```env
MERIDIAN_AGENT_TURN_TIMEOUT_SECONDS=60
MERIDIAN_MODEL_REQUEST_TIMEOUT_SECONDS=45
```

Agent Chat 使用 Meridian 平台 PostgreSQL，默认连接开发环境 `127.0.0.1:15432/meridian`：

```env
MERIDIAN_CHAT_DB_ENABLED=true
MERIDIAN_DB_HOST=127.0.0.1
MERIDIAN_DB_PORT=15432
MERIDIAN_DB_USER=root
MERIDIAN_DB_PASSWORD=jayleonc
MERIDIAN_DB_NAME=meridian
```

Nexus 内部 Agent 结构：

```text
nexus/src/agent/
  api.py        # /api/chat 路由
  runtime.py    # 工具调用循环
  providers.py  # LangChain 模型适配
  tools.py      # 工具 schema 与参数校验
  sessions.py   # 会话存储接口（MVP 为内存）
  models.py     # API 数据模型
  prompts.py    # 系统提示词
```

`scripts/dev.sh` 会自动加载仓库根目录 `.env`。默认 `MERIDIAN_UVICORN_ACCESS_LOG=false`，本地与容器启动都不会刷 `/health` 这类访问日志；需要调试 HTTP 请求时改成 `true` 后重启服务。

## 文档

- [架构全景](docs/ARCHITECTURE.md)
- [命名与组件职责](docs/NAMING.md)
- [分阶段规划](docs/ROADMAP.md)
- [技术决策记录](docs/DECISIONS.md)
