import { useEffect, useMemo, useState } from "react";
import {
  nexus,
  type NexusRegistry,
  type NexusRegistryStatus,
  type NexusToolManifest,
} from "../../api/client";
import { useApp } from "../../context/AppContext";

type FilterKey = "all" | "approved" | "pending" | "dynamic" | "agent";

interface ToolRow extends NexusToolManifest {
  serviceName: string;
  serviceVersion: string;
  serviceBaseUrl: string;
  dynamic: boolean;
}

const FILTERS: Array<{ key: FilterKey; label: string; title: string }> = [
  { key: "all", label: "全部 All", title: "显示 registry manifest 中的全部工具。" },
  { key: "approved", label: "已批准 Approved", title: "status=approved，允许进入 Nexus gateway pipeline。" },
  { key: "pending", label: "待审批 Pending", title: "尚未批准或被拒绝，不应对 Agent 或 MCP 客户端开放。" },
  { key: "dynamic", label: "MCP 可发现", title: "已动态注册为 Nexus MCP tool，客户端 tools/list 可以发现。" },
  { key: "agent", label: "Agent 可用", title: "manifest 声明 exposure.agent=true，表示允许进入 Agent 工具面。" },
];

export default function NexusPage() {
  const { toast } = useApp();
  const [registry, setRegistry] = useState<NexusRegistry | null>(null);
  const [status, setStatus] = useState<NexusRegistryStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<FilterKey>("all");
  const [serviceFilter, setServiceFilter] = useState("all");
  const [selectedName, setSelectedName] = useState("");

  async function load() {
    setLoading(true);
    setError("");
    try {
      const [registryData, statusData] = await Promise.all([
        nexus.registry(),
        nexus.registryStatus(),
      ]);
      setRegistry(registryData);
      setStatus(statusData);
      const allTools = flattenTools(registryData, statusData.dynamic_tools_registered);
      setSelectedName((current) =>
        current && allTools.some((tool) => tool.name === current)
          ? current
          : allTools[0]?.name ?? ""
      );
    } catch (e) {
      const message = e instanceof Error ? e.message : "Nexus registry 加载失败";
      setError(message);
      toast("error", message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  const tools = useMemo(
    () => flattenTools(registry, status?.dynamic_tools_registered ?? []),
    [registry, status]
  );

  const services = useMemo(
    () => Array.from(new Set(tools.map((tool) => tool.serviceName))).sort(),
    [tools]
  );

  const filteredTools = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return tools.filter((tool) => {
      if (serviceFilter !== "all" && tool.serviceName !== serviceFilter) return false;
      if (filter === "approved" && tool.status !== "approved") return false;
      if (filter === "pending" && tool.status === "approved") return false;
      if (filter === "dynamic" && !tool.dynamic) return false;
      if (filter === "agent" && !tool.exposure?.agent) return false;
      if (!needle) return true;
      return [
        tool.name,
        tool.serviceName,
        tool.adapter,
        tool.risk,
        tool.method,
        tool.path,
        tool.description,
        toolPurpose(tool),
      ]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(needle));
    });
  }, [filter, query, serviceFilter, tools]);

  const selected = tools.find((tool) => tool.name === selectedName) ?? filteredTools[0] ?? tools[0];
  const approvedCount = tools.filter((tool) => tool.status === "approved").length;
  const dynamicCount = status?.dynamic_tools_registered.length ?? 0;
  const pendingCount = tools.length - approvedCount;

  return (
    <>
      <div className="page-header">
        <h2>Nexus</h2>
        <div className="page-desc">工具注册中心 Registry / 清单 Manifest / 受控网关 Gateway Pipeline</div>
        <div className="page-toolbar">
          <input
            className="input"
            style={{ maxWidth: 320 }}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="工具名 / 服务 / 风险级别"
          />
          <select
            className="input"
            style={{ maxWidth: 160 }}
            value={serviceFilter}
            onChange={(event) => setServiceFilter(event.target.value)}
          >
            <option value="all">全部服务</option>
            {services.map((service) => (
              <option key={service} value={service}>
                {service}
              </option>
            ))}
          </select>
          <button className="btn btn-ghost btn-sm" onClick={load} disabled={loading}>
            {loading ? <span className="spinner" /> : "刷新"}
          </button>
        </div>
      </div>

      <div className="page-body">
        <div className="g4 mb-md">
          <Metric label="Manifest 工具" value={tools.length || "—"} tone="teal" title="registry manifest 中声明的工具总数。" />
          <Metric label="MCP 可发现" value={dynamicCount || "—"} tone="emerald" title="已动态注册到 Nexus MCP Server 的工具数，MCP 客户端可通过 tools/list 发现。" />
          <Metric label="待审批" value={pendingCount || 0} tone={pendingCount > 0 ? "amber" : "emerald"} title="status 不是 approved 的工具数，后续需要审批流程处理。" />
          <Metric label="审计记录" value={status?.audit_records ?? "—"} tone="violet" title="当前进程内记录到的 ToolGateway 调用审计条数。" />
        </div>

        <div className="card mb-md nexus-help-card">
          <div className="card-body nexus-policy-strip">
            <div>
              <div className="label-with-help mb-xs">
                <span className="field-label inline-label">工具暴露 Tool Exposure</span>
                <HelpTip text="Nexus 是受控工具网关，只暴露 registry allowlist 中的工具，不透明透传下游所有 MCP 工具。" />
              </div>
              <div className="nexus-policy-main">
                <span className="badge badge-emerald">{registry?.tool_exposure.mode ?? "controlled_gateway"}</span>
                <span className="badge badge-dim">{registry?.tool_exposure.source ?? "nexus_registry_allowlist"}</span>
                <span className={registry?.tool_exposure.transparent_downstream_mcp ? "badge badge-coral" : "badge badge-teal"}>
                  透明透传={String(Boolean(registry?.tool_exposure.transparent_downstream_mcp))}
                </span>
              </div>
            </div>
            <div>
              <div className="label-with-help mb-xs">
                <span className="field-label inline-label">发现同步 Discovery Sync</span>
                <HelpTip text="MCP 协议支持 notifications/tools/list_changed，客户端收到后应重新 tools/list。Nexus 当前还未发这个通知；现阶段修改已有工具 schema 或 adapter 时使用重启作为 fallback。" />
              </div>
              <div className="nexus-policy-main">
                <span className={status?.reload.enabled ? "badge badge-emerald" : "badge badge-dim"}>
                  {status?.reload.enabled ? "通知待接入" : "重启 fallback"}
                </span>
                <span className="mono muted">{status?.reload.strategy ?? "restart_or_additive_reload"}</span>
              </div>
            </div>
          </div>
        </div>

        <div className="seg-tabs mb-md">
          {FILTERS.map((item) => (
            <button
              key={item.key}
              className={`seg-tab ${filter === item.key ? "active" : ""}`}
              onClick={() => setFilter(item.key)}
              title={item.title}
            >
              {item.label}
            </button>
          ))}
        </div>

        {error && (
          <div className="card mb-md">
            <div className="card-body">
              <span className="badge badge-coral">{error}</span>
            </div>
          </div>
        )}

        <div className="nexus-grid">
          <div className="card">
            <div className="card-head">
              <h3>工具 Tools</h3>
              <span className="badge badge-teal">{filteredTools.length}</span>
            </div>
            <div className="card-body flush nexus-table-wrap">
              {loading ? (
                <div className="empty">
                  <span className="spinner" />
                  <div className="empty-text">加载中</div>
                </div>
              ) : filteredTools.length > 0 ? (
                <table className="dtable nexus-tools-table">
                  <colgroup>
                    <col className="tool-col" />
                    <col className="service-col" />
                    <col className="status-col" />
                    <col className="exposure-col" />
                    <col className="risk-col" />
                    <col className="adapter-col" />
                  </colgroup>
                  <thead>
                    <tr>
                      <th>工具 Tool</th>
                      <th>服务 Service</th>
                      <th>状态 Status</th>
                      <th>暴露 Exposure</th>
                      <th>风险 Risk</th>
                      <th>适配器 Adapter</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredTools.map((tool) => (
                      <tr
                        key={tool.name}
                        className={selected?.name === tool.name ? "selected-row" : ""}
                        onClick={() => setSelectedName(tool.name)}
                      >
                        <td className="tool-cell">
                          <div className="tool-main-line">
                            <span className="mono table-strong tool-name" title={tool.name}>{tool.name}</span>
                            <span className="badge badge-dim method-chip">{tool.method ?? "—"}</span>
                          </div>
                          <div className="table-sub table-ellipsis" title={tool.path ?? ""}>{tool.path ?? ""}</div>
                          <div className="table-sub table-ellipsis" title={toolPurpose(tool)}>
                            {toolPurpose(tool)}
                          </div>
                        </td>
                        <td className="nowrap-cell">{tool.serviceName}</td>
                        <td className="nowrap-cell"><StatusBadge tool={tool} /></td>
                        <td className="nowrap-cell"><ExposureBadges tool={tool} compact /></td>
                        <td className="nowrap-cell"><span className="badge badge-dim">{tool.risk ?? "read"}</span></td>
                        <td className="nowrap-cell"><span className="badge badge-violet">{tool.adapter}</span></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <div className="empty">
                  <div className="empty-text">没有匹配工具</div>
                </div>
              )}
            </div>
          </div>

          <ToolDetail tool={selected} />
        </div>
      </div>
    </>
  );
}

function Metric({ label, value, tone, title }: { label: string; value: string | number; tone: "teal" | "emerald" | "amber" | "violet"; title: string }) {
  return (
    <div className="card nexus-help-card">
      <div className="stat">
        <div className={`stat-val ${tone}`}>{value}</div>
        <div className="stat-label label-with-help center-label">
          <span>{label}</span>
          <HelpTip text={title} />
        </div>
      </div>
    </div>
  );
}

function ToolDetail({ tool }: { tool?: ToolRow }) {
  if (!tool) {
    return (
      <div className="card">
        <div className="empty">
          <div className="empty-text">未选择工具</div>
        </div>
      </div>
    );
  }

  const inputProperties = Object.keys((tool.input_schema?.properties as Record<string, unknown> | undefined) ?? {});
  const required = (tool.input_schema?.required as string[] | undefined) ?? [];

  return (
    <div className="card nexus-detail">
      <div className="card-head">
        <h3>清单 Manifest</h3>
        <StatusBadge tool={tool} />
      </div>
      <div className="card-body">
        <div className="detail-title mono">{tool.name}</div>
        <div className="detail-desc">{toolPurpose(tool)}</div>

        <div className="detail-grid mt-md">
          <Field label="服务 Service" value={`${tool.serviceName} ${tool.serviceVersion}`} />
          <Field label="版本 Version" value={tool.version ?? "v1"} />
          <Field label="方法 Method" value={tool.method ?? "—"} />
          <Field label="适配器 Adapter" value={tool.adapter} />
          <Field label="超时 Timeout" value={`${tool.timeout_seconds ?? 30}s / ${tool.downstream_timeout_seconds ?? tool.timeout_seconds ?? 30}s`} />
          <Field label="响应上限 Max Response" value={`${tool.max_response_bytes ?? 12000} bytes`} />
          <Field label="路径 Path" value={tool.path ?? "—"} mono wide />
          <Field label="基础地址 Base URL" value={tool.serviceBaseUrl} mono wide />
        </div>

        <div className="detail-section">
          <div className="label-with-help mb-sm">
            <span className="field-label inline-label">暴露状态 Exposure</span>
            <HelpTip text="MCP 可发现表示客户端 tools/list 能看到；Agent 可用表示允许进入 Agent 工具面；动态注册表示当前 Nexus 进程已经注册 handler。" />
          </div>
          <ExposureBadges tool={tool} />
        </div>

        <div className="detail-section">
          <div className="label-with-help mb-sm">
            <span className="field-label inline-label">权限 Scopes</span>
            <HelpTip text="调用方必须具备这些 scope，ToolGateway 才会执行 adapter。" />
          </div>
          <div className="badge-row">
            {(tool.required_scopes?.length ? tool.required_scopes : ["无 none"]).map((scope) => (
              <span key={scope} className="badge badge-amber">{scope}</span>
            ))}
          </div>
        </div>

        <div className="detail-section">
          <div className="label-with-help mb-sm">
            <span className="field-label inline-label">入参结构 Input Schema</span>
            <HelpTip text="这些字段来自 manifest.input_schema，会被用于动态 MCP handler 的参数结构。" />
          </div>
          <div className="schema-grid">
            {inputProperties.length > 0 ? inputProperties.map((name) => (
              <div key={name} className="schema-chip">
                <span className="mono">{name}</span>
                {required.includes(name) && <span className="badge badge-coral">必填</span>}
              </div>
            )) : (
              <span className="muted">无字段 empty</span>
            )}
          </div>
        </div>

        <div className="detail-section">
          <div className="label-with-help mb-sm">
            <span className="field-label inline-label">敏感字段 Sensitive Fields</span>
            <HelpTip text="这些字段会在响应和审计记录中被 ToolGateway 尽量脱敏。" />
          </div>
          <div className="badge-row">
            {(tool.sensitive_fields?.length ? tool.sensitive_fields : ["无 none"]).map((field) => (
              <span key={field} className="badge badge-dim">{field}</span>
            ))}
          </div>
        </div>

        <details className="detail-section detail-collapse">
          <summary className="label-with-help mb-sm">
            <span className="field-label inline-label">审批信息 Approval</span>
            <HelpTip text="当前是只读展示。后续 Console 会在这里接入 approve / reject / reload 操作。" />
          </summary>
          <pre className="json-preview">{JSON.stringify(tool.approval ?? {}, null, 2)}</pre>
        </details>
      </div>
    </div>
  );
}

function Field({ label, value, mono = false, wide = false }: { label: string; value: string; mono?: boolean; wide?: boolean }) {
  return (
    <div className={wide ? "detail-field wide" : "detail-field"}>
      <div className="field-label">{label}</div>
      <div className={mono ? "mono detail-value" : "detail-value"}>{value}</div>
    </div>
  );
}

function StatusBadge({ tool }: { tool: ToolRow }) {
  if (tool.status === "approved") return <span className="badge badge-emerald">已批准 approved</span>;
  if (tool.status === "rejected") return <span className="badge badge-coral">已拒绝 rejected</span>;
  return <span className="badge badge-warn">待审批 {tool.status ?? "pending"}</span>;
}

function ExposureBadges({ tool, compact = false }: { tool: ToolRow; compact?: boolean }) {
  return (
    <div className={compact ? "exposure-stack compact" : "badge-row"}>
      <span
        className={tool.exposure?.mcp ? "badge badge-emerald" : "badge badge-dim"}
        title="MCP 可发现：Nexus MCP Server 会把这个工具放进 tools/list。"
      >
        {compact ? "MCP" : `MCP 可发现=${String(Boolean(tool.exposure?.mcp))}`}
      </span>
      <span
        className={tool.exposure?.agent ? "badge badge-teal" : "badge badge-dim"}
        title="Agent 可用：允许进入 Meridian Agent 工具面；不是说它属于 Agent 模块。"
      >
        {compact ? "Agent" : `Agent 可用=${String(Boolean(tool.exposure?.agent))}`}
      </span>
      <span
        className={tool.dynamic ? "badge badge-emerald" : "badge badge-dim"}
        title="动态注册：当前 Nexus 进程已经为它注册了 MCP handler。"
      >
        {compact ? "Reg" : `动态注册=${String(tool.dynamic)}`}
      </span>
    </div>
  );
}

function HelpTip({ text }: { text: string }) {
  return (
    <button type="button" className="help-tip" aria-label={text}>
      ?
      <span className="help-bubble">{text}</span>
    </button>
  );
}

function toolPurpose(tool: NexusToolManifest | ToolRow): string {
  const purpose: Record<string, string> = {
    "atlas.health.v1": "检查 Atlas 是否在线，用于 Nexus/Console 健康检查，不给 Agent 作为诊断工具。",
    "atlas.list_services": "列出 Atlas 发现的业务服务、部署路径、日志路径和关联数据库，帮助 Agent 理解系统边界。",
    "atlas.search_meta": "按关键词搜索表、字段、服务和语义，用于把日志里的业务词映射到可查对象。",
    "atlas.get_table": "读取某张表的字段、索引、注释和语义，供 Lens 建模或 Agent 判断字段含义。",
    "probe.search_by_request_id": "按 request_id 汇总日志时间线、错误/警告和服务路径，是排查一次请求的主入口。",
    "probe.search_logs": "按关键词、服务和时间范围搜索日志，适合 request_id 不明确时补证据。",
    "probe.tail_errors": "查看近期错误日志，适合巡检和发现当前正在发生的问题。",
    "probe.tail_service_logs": "查看某个服务的近期日志，适合聚焦单服务排查。",
    "probe.list_services": "列出 Probe 当前能读取日志的服务，用于选择后续日志查询范围。",
    "probe.context_around_match": "读取某条命中日志前后上下文，避免只看单行导致误判。",
    "probe.search_ops_logs": "跨白名单主机搜索运维日志，适合多机器问题；当前仍受 ops 配置约束。",
    "lens.list_entities": "列出已经人工治理并启用的业务实体；Agent 只能发现这些实体。",
    "lens.describe_entity": "查看业务实体字段、敏感性、可筛选/可排序策略和查询约束。",
    "lens.query": "执行 Lens 只读 DSL 查询；明细查询必须有筛选或时间范围，Preview 只返回安全样本。",
  };
  return purpose[tool.name] || tool.description || "这个工具尚未补充中文用途说明。";
}

function flattenTools(registry: NexusRegistry | null, dynamicNames: string[]): ToolRow[] {
  const dynamic = new Set(dynamicNames);
  if (!registry) return [];
  return registry.service.flatMap((service) =>
    (service.tool_manifests ?? []).map((tool) => ({
      ...tool,
      serviceName: service.name,
      serviceVersion: service.version,
      serviceBaseUrl: service.base_url,
      dynamic: dynamic.has(tool.name),
    }))
  );
}
