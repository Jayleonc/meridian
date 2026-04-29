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

如果开发服务器 Node 版本太旧，可以在本地构建 Console，再把静态产物传到服务器：

```bash
# 本地机器：构建并打包 console/dist
./scripts/package-console-dist.sh
scp .meridian/artifacts/console-dist.tar.gz <dev-server>:/opt/meridian/

# 开发服务器：解包静态产物并跳过前端构建
cd /opt/meridian
./scripts/install-console-dist.sh /opt/meridian/console-dist.tar.gz
./scripts/dev-server.sh --skip-console-build
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
