# Meridian

MCP（Model Context Protocol）驱动的智能运维观测平台。

## 项目结构

| 模块 | 职责 |
|------|------|
| **atlas** | Meta MCP 服务 — 元数据管理与服务注册 |
| **probe** | 日志观测 MCP — 日志采集、搜索与分析 |
| **lens** | 数据查询 MCP — DSL 风控规则引擎 |
| **trace** | 链路关联 MCP — 分布式追踪与链路分析 |
| **nexus** | MCP 网关 — 请求路由与协议转发 |
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

Console 静态资源由 Nexus 托管，Console 的所有后端请求仍走 `/api/*`、`/svc/*`、`/api/chat/*`、`/mcp/*`，不需要额外开放 `3010`。

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

开发服务器使用独立配置文件，不和模块本地 `settings/config.yaml` 混用：

```text
deploy/dev-server/atlas.config.yaml
deploy/dev-server/probe.config.yaml
deploy/dev-server/lens.config.yaml
```

`dev-server.sh` 会默认设置 `MERIDIAN_ATLAS_CONFIG`、`MERIDIAN_PROBE_CONFIG` 和 `MERIDIAN_LENS_CONFIG` 指向这些文件。Probe 默认按 `Asia/Shanghai` 业务日志时区查找 `/data/brick/log/YYYYMMDDHH.log` 小时文件；如果服务器日志文件名使用其他时区，修改 `deploy/dev-server/probe.config.yaml` 的 `time.log_timezone`。Atlas 在开发服务器配置中不会每次启动都重新全量采集业务 MySQL，而是优先从 Meridian PostgreSQL 恢复最近一次 schema 快照；需要重新采集时再通过 Console / API / MCP 手动 refresh。

如果开发服务器 Node 版本太旧，可以直接使用仓库内预构建的 Console 静态产物：

```bash
cd /opt/meridian
git pull
./scripts/install-console-dist.sh deploy/console-dist.tar.gz
./scripts/dev-server.sh --skip-console-build
```

如果需要更新这个预构建包，在有 Node >= 20 的本地机器运行：

```bash
./scripts/package-console-dist.sh
cp .meridian/artifacts/console-dist.tar.gz deploy/console-dist.tar.gz
```

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

这条链路不依赖外部大模型，CLI 会通过 `http://127.0.0.1:3000/mcp/stream/` 调 Nexus，再由 Nexus 转发到 Probe。

Console 本地开发同样经由 Nexus 转发后端请求，不再直接连接 Atlas / Probe / Lens。

## Agent Chat

Console 的 `Agent` 页面调用 Nexus 的 `/api/chat/*`。这套接口是 Meridian 自己的会话协议，不绑定 OpenAI Responses / Agents SDK。

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

Agent 单轮请求默认最多等待 60 秒，单次模型请求默认最多等待 45 秒，避免模型网关或网络问题让 Console 一直停在 Thinking：

```env
MERIDIAN_AGENT_TURN_TIMEOUT_SECONDS=60
MERIDIAN_MODEL_REQUEST_TIMEOUT_SECONDS=45
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
