# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## 项目概述

Meridian 是一个 MCP（Model Context Protocol）驱动的智能运维观测平台。Monorepo 结构，包含 7 个 Python 微服务、1 个 React 前端和共享库。

## 架构

**五层诊断模型**：L1 观测（Probe）→ L2 关联（Trace）→ L3 语义（Atlas/Codex）→ L4 诊断 → L5 处置

**服务列表**（全部使用 FastMCP + FastAPI）：

| 服务 | 内部端口 | 职责 | 状态 |
|------|---------|------|------|
| nexus | 3000 | MCP 网关 — 单入口、服务代理、Agent API、DevOps MCP | **已实现 MVP** |
| atlas | 3001 | 元数据 MCP — Schema 管理与服务注册 | **已实现** |
| probe | 3002 | 日志观测 MCP — 日志搜索与分析 | **已实现** |
| lens | 3003 | 数据查询 MCP — 业务实体映射 | **已实现** |
| trace | 3004 | 链路关联 MCP — 分布式追踪 | Stub |
| console | 由 nexus 托管 | React 19 + TypeScript + Vite 6 前端 | **已实现** |
| codex | — | 诊断知识库 | Stub |
| forge | — | MCP Builder — 模板驱动配置生成（Jinja2） | Stub |

**注意**：所有内部端口都通过 `.env` 环境变量配置（见 `docs/DEPLOYMENT.md`）。外部仅暴露 **3000** 端口。

**数据库**：PostgreSQL 17（平台存储：快照、标注、变更日志、审计）+ MySQL 8.0（业务 Schema，只读，通过 `information_schema`）

## 常用命令

```bash
# ── 启动服务（本地开发，推荐用 uv）──
./scripts/dev.sh atlas                  # 启动 Atlas
./scripts/dev.sh probe                  # 启动 Probe
./scripts/dev.sh atlas probe            # 同时启动多个
./scripts/dev.sh --install atlas        # 先装依赖再启动

# 或者手动启动（端口由 .env 配置，默认 300x 系列）
cd atlas && uv run uvicorn app.main:app --reload
cd probe && uv run uvicorn app.main:app --reload

# ── Docker Compose 部署（单端口 3000 暴露）──
# 生成 .env（使用默认推荐端口 300x 系列）
cp .env.example .env
# 如果有端口冲突，编辑 .env 修改对应端口
docker-compose up -d

# ── 冒烟测试（AI 和人都可以用）──
python3 scripts/smoke-test.py           # 测试所有服务 + 数据库连通性
python3 scripts/smoke-test.py atlas     # 只测 Atlas
python3 scripts/smoke-test.py --mysql   # 只测 MySQL
python3 scripts/smoke-test.py --pg      # 只测 PostgreSQL

# ── 单元测试 ──
cd atlas && uv run pytest
cd atlas && uv run pytest tests/test_xxx.py -v           # 单个测试文件
cd atlas && uv run pytest tests/test_xxx.py::test_name -v  # 单个测试

# ── 代码检查 ──
cd atlas && uv run ruff check .
cd atlas && uv run ruff format .

# ── 前端 ──
cd console && npm run dev      # 开发服务器
cd console && npm run build    # 生产构建
```

## 部署与端口配置

详见 `docs/DEPLOYMENT.md` — 完整的端口规划、Docker Compose 配置、环境变量说明。

## 本地环境

- **MySQL**：Docker 容器 `local-mysql`（root/root, port 3306, database test）— 业务数据，只读
- **PostgreSQL**：Docker 容器 `ai-assistant-postgres`（root/jayleonc, port **15432**, database meridian）— Meridian 平台存储（快照、标注、变更日志、审计）；不启动时 Atlas 自动降级为纯内存模式
- **外部暴露端口**：`3000`（Nexus 网关 + Console 前端）— 所有请求通过此端口
- **内部服务端口**（完全可配置，见 `docs/DEPLOYMENT.md`）：
  - Nexus: 3000 (网关 + Console 静态资源)
  - Atlas: 3001 (元数据)
  - Probe: 3002 (日志)
  - Lens: 3003 (数据查询)
  - Trace: 3004 (链路)
  - Console: 由 Nexus 托管；本地 Vite 开发时才单独运行
  - PostgreSQL: 15432（平台库 host port；容器内 5432）
  - MySQL: 3306（本地 mock 或业务库只读入口）

## 代码规范

- **Python**：snake_case；全局 async/await
- **React**：PascalCase 组件，camelCase 函数
- **API 路径**：kebab-case
- **数据库表名**：单数命名（如 `schema_snapshot`，不是 `schema_snapshots`）
- **构建系统**：所有 Python 服务使用 hatchling；Atlas/Probe 需要 Python 3.12+，其余 3.11+

## 核心模式（Atlas/Probe 作为参考实现）

- **MCP 工具**：`@mcp.tool()` 装饰的 async 函数挂在 `FastMCP` 实例上；返回 JSON 字符串（`json.dumps()`），不返回 dict
- **配置**：YAML 配置文件加载到嵌套 Pydantic 模型；通过 `load_settings()` 单例加载
- **数据库适配器**：Repository 模式 + 连接池管理（aiomysql / asyncpg）；PG 不可用时优雅降级
- **服务层**：内存缓存 + PG 持久化；按需加载
- **审计**：`@audited()` 装饰器双写日志（文件 JSON Lines + PostgreSQL）；PG 异常不影响主流程
- **传输层**：SSE 在 `/mcp/sse`，POST 在 `/mcp/messages/`，StreamableHTTP 作为备用
- **FastAPI 生命周期**：通过 async context manager 在启动时初始化 DB 连接池，关闭时释放
- **安全**：路径白名单校验、输入正则验证、不使用 shell=True、日志截断限制、敏感信息脱敏

## 规格说明

每个服务在 `docs/specs/{service}-spec.md` 中有详细的规格文档，定义了工具、数据模型和集成点。**实现任何服务前，务必先阅读对应的 spec**。

## 设计决策

- Python 作为主语言（DR-001）
- Lens 使用自定义 DSL，不用原始 SQL（DR-002）
- MCP 作为所有服务通信的核心协议（DR-003）
- 双数据库策略：MySQL（业务，只读）+ PostgreSQL（平台存储）（DR-004）
- AI 是证据组织者/助手，不是自主决策者（DR-006）

## 原始设计讨论（temp/ 目录）

当你对项目的设计理念、架构动机或方向感到迷茫时，可以阅读 `temp/` 目录下的原始讨论记录：

| 文件 | 内容 |
|------|------|
| `architecture.html` | 架构全景可视化 — 交互式 HTML 页面，展示 6 层架构、10+ 核心组件、4 条数据流，以及命名词典 |
| `chat-with-claude.md` | 与 Claude 的技术讨论 — 语义层设计、DSL vs SQL 决策、MCP 模板化生成、变更同步策略、Atlas 优先的理由 |
| `chat-with-chatgpt.md` | 与 ChatGPT 的战略讨论 — 项目可行性评估、单人执行风险、MVP 策略（Atlas + Probe + Console 先行）、个人成长价值 |
| `from-probe-to-diagnosis-system.md` | 从 Probe 到诊断系统的演进 — 五层诊断能力模型、知识沉淀模板、分阶段实施路线（最详细的执行指南） |

这些文件记录了项目从构想到落地的完整思考过程，是理解「为什么这样设计」的第一手资料。
