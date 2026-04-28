# Constitution

> Meridian 工程宪法 — 所有代码必须遵守的不可变原则。
>
> 本文档优先级高于任何 spec 或 plan。当它们冲突时，以本文档为准。

## 1. Python 微服务最佳实践

### 1.1 分层架构（每个服务必须遵守）

```
app/
├── adapters/       # I/O 边界：数据库、外部 API、文件系统
├── api/            # HTTP 路由（FastAPI Router）
├── core/           # 配置、常量、共享类型
├── mcp/            # MCP 工具定义 + 传输层
├── schemas/        # Pydantic 模型（输入/输出/领域）
├── services/       # 业务逻辑（纯函数优先，无 I/O）
├── settings/       # YAML 配置文件
└── utils/          # 工具函数（审计、日志等）
```

**依赖方向单向流动**：`mcp/api → services → adapters`。禁止反向依赖。

### 1.2 适配器模式（Adapter Pattern）

所有外部 I/O 必须通过适配器隔离：
- 适配器对外暴露 **Protocol（协议类）**，不暴露具体实现
- 新增数据源 = 新增适配器实现，不改 service 层
- 连接池生命周期由 FastAPI lifespan 管理
- 适配器不可用时必须优雅降级，不得抛出未捕获异常

### 1.3 配置驱动

- 所有可变参数必须走 YAML 配置 + Pydantic 模型校验
- 配置通过 `load_settings()` 单例加载，不允许散落的硬编码
- 环境差异通过配置文件切换，不通过 if/else 分支

### 1.4 异步优先

- 所有 I/O 操作必须 async/await
- 同步阻塞操作（如 XML-RPC）必须包装在 `asyncio.to_thread()` 中
- 连接池使用异步驱动（aiomysql、asyncpg）

### 1.5 安全基线

- 路径白名单校验、输入正则验证
- 不使用 `shell=True`
- 日志截断限制（防日志注入）
- 敏感信息脱敏（手机号、身份证、密码、token）
- SQL 查询全部参数化，禁止字符串拼接

## 2. 扩展性原则

### 2.1 Provider 模式（适用于有多种后端的场景）

当某个能力有多种实现时（如数据库类型、服务发现方式），使用 Provider 模式：

```python
class SomeProvider(Protocol):
    """协议定义 — 放在 schemas/ 或 core/"""
    async def do_something(self, ...) -> Result: ...

# 具体实现放在 adapters/
class MySQLProvider:
    async def do_something(self, ...) -> Result: ...

class PostgreSQLProvider:
    async def do_something(self, ...) -> Result: ...
```

- 配置决定加载哪些 Provider
- Service 层只依赖 Protocol，不依赖具体实现
- 新增 Provider 不需要修改现有代码

### 2.2 注册表模式（Registry）

当需要按名称路由到不同实现时，使用注册表：

```python
_registry: dict[str, SomeProvider] = {}

def register(name: str, provider: SomeProvider): ...
def get(name: str) -> SomeProvider | None: ...
```

### 2.3 开放-封闭

- 对扩展开放：新增数据源类型、新增服务发现方式、新增 MCP 工具 — 只加代码
- 对修改封闭：加新类型不需要改现有适配器、不需要改 service 层逻辑

## 3. MCP 服务规范

### 3.1 工具定义

- `@mcp.tool()` 装饰的 async 函数
- 返回 `json.dumps()` 字符串，不返回 dict
- 每个工具配 `@audited()` 装饰器

### 3.2 传输层

- SSE: `/mcp/sse` + `/mcp/messages/`
- StreamableHTTP: `/mcp/stream`（备用）
- 传输层代码在 `mcp/sse.py`，不与业务逻辑混合

### 3.3 审计

- 双写：本地 JSON Lines 文件 + PostgreSQL
- PG 不可用不影响主流程（降级到纯文件）

## 4. 数据库策略

### 4.1 双角色数据库

| 角色 | 用途 | 访问模式 | 驱动 |
|------|------|----------|------|
| 业务数据库 | 承载业务数据 | **只读** | aiomysql / asyncpg（按类型） |
| 平台数据库 | Meridian 自身存储 | 读写 | asyncpg（固定 PostgreSQL） |

**关键**：业务数据库不限于 MySQL。任何 RDBMS 都可以是业务数据源，只要有对应的只读适配器。

### 4.2 表命名

- 单数命名：`entity_definition`，不是 `entity_definitions`
- snake_case

### 4.3 降级策略

- 平台 PG 不可用 → 降级到纯内存模式（无持久化）
- 业务数据库不可用 → 返回空结果 + 告警日志

## 5. 服务发现

### 5.1 Provider 抽象

服务发现不绑定任何特定进程管理器。通过 Provider 模式支持：
- Supervisor（XML-RPC + 日志扫描）
- Docker（docker API）
- Systemd（systemctl）
- 静态配置（手动注册）
- 未来：Kubernetes

### 5.2 Atlas 是服务发现的权威源

- Atlas 负责采集和管理服务列表
- 其他服务（Probe、Trace）通过 Atlas 获取服务信息，不自行发现
- 本地开发时，如果 Atlas 不可用，允许降级到静态配置

## 6. 测试标准

- 纯逻辑（DSL 编译、验证）：单元测试，不需要数据库
- 适配器：集成测试，需要真实数据库连接
- MCP 工具：端到端冒烟测试（`scripts/smoke-test.py`）
- 新增 Provider 必须附带对应测试

## 7. 不做的事

- 不过度抽象：一个实现不需要 Protocol，两个以上才需要
- 不提前优化：先正确，再快速
- 不自造轮子：优先用生态库（FastMCP、Pydantic、asyncpg）
- 不跨服务共享状态：服务间通过 MCP 通信，不共享内存或数据库表
