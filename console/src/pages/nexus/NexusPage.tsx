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

const FILTERS: Array<{ key: FilterKey; label: string }> = [
  { key: "all", label: "全部" },
  { key: "approved", label: "Approved" },
  { key: "pending", label: "Pending" },
  { key: "dynamic", label: "MCP" },
  { key: "agent", label: "Agent" },
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
        <div className="page-desc">Registry / Manifest / Gateway Pipeline</div>
        <div className="page-toolbar">
          <input
            className="input"
            style={{ maxWidth: 320 }}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="tool / service / risk"
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
          <Metric label="Manifest Tools" value={tools.length || "—"} tone="teal" />
          <Metric label="Dynamic MCP" value={dynamicCount || "—"} tone="emerald" />
          <Metric label="Pending" value={pendingCount || 0} tone={pendingCount > 0 ? "amber" : "emerald"} />
          <Metric label="Audit Records" value={status?.audit_records ?? "—"} tone="violet" />
        </div>

        <div className="card mb-md">
          <div className="card-body nexus-policy-strip">
            <div>
              <div className="field-label mb-xs">Tool Exposure</div>
              <div className="nexus-policy-main">
                <span className="badge badge-emerald">{registry?.tool_exposure.mode ?? "controlled_gateway"}</span>
                <span className="badge badge-dim">{registry?.tool_exposure.source ?? "nexus_registry_allowlist"}</span>
                <span className={registry?.tool_exposure.transparent_downstream_mcp ? "badge badge-coral" : "badge badge-teal"}>
                  transparent={String(Boolean(registry?.tool_exposure.transparent_downstream_mcp))}
                </span>
              </div>
            </div>
            <div>
              <div className="field-label mb-xs">Reload</div>
              <div className="nexus-policy-main">
                <span className={status?.reload.enabled ? "badge badge-emerald" : "badge badge-dim"}>
                  {status?.reload.enabled ? "enabled" : "restart"}
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
              <h3>Tools</h3>
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
                  <thead>
                    <tr>
                      <th>Tool</th>
                      <th>Service</th>
                      <th>Status</th>
                      <th>Risk</th>
                      <th>Adapter</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredTools.map((tool) => (
                      <tr
                        key={tool.name}
                        className={selected?.name === tool.name ? "selected-row" : ""}
                        onClick={() => setSelectedName(tool.name)}
                      >
                        <td>
                          <div className="mono table-strong">{tool.name}</div>
                          <div className="table-sub">{tool.method ?? "—"} {tool.path ?? ""}</div>
                        </td>
                        <td>{tool.serviceName}</td>
                        <td><StatusBadge tool={tool} /></td>
                        <td><span className="badge badge-dim">{tool.risk ?? "read"}</span></td>
                        <td><span className="badge badge-violet">{tool.adapter}</span></td>
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

function Metric({ label, value, tone }: { label: string; value: string | number; tone: "teal" | "emerald" | "amber" | "violet" }) {
  return (
    <div className="card">
      <div className="stat">
        <div className={`stat-val ${tone}`}>{value}</div>
        <div className="stat-label">{label}</div>
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
        <h3>Manifest</h3>
        <StatusBadge tool={tool} />
      </div>
      <div className="card-body">
        <div className="detail-title mono">{tool.name}</div>
        <div className="detail-desc">{tool.description || "—"}</div>

        <div className="detail-grid mt-md">
          <Field label="Service" value={`${tool.serviceName} ${tool.serviceVersion}`} />
          <Field label="Base URL" value={tool.serviceBaseUrl} mono />
          <Field label="Adapter" value={tool.adapter} />
          <Field label="Version" value={tool.version ?? "v1"} />
          <Field label="Method" value={tool.method ?? "—"} />
          <Field label="Path" value={tool.path ?? "—"} mono />
          <Field label="Timeout" value={`${tool.timeout_seconds ?? 30}s / ${tool.downstream_timeout_seconds ?? tool.timeout_seconds ?? 30}s`} />
          <Field label="Max Response" value={`${tool.max_response_bytes ?? 12000} bytes`} />
        </div>

        <div className="detail-section">
          <div className="field-label mb-sm">Exposure</div>
          <div className="badge-row">
            <span className={tool.exposure?.mcp ? "badge badge-emerald" : "badge badge-dim"}>mcp={String(Boolean(tool.exposure?.mcp))}</span>
            <span className={tool.exposure?.agent ? "badge badge-teal" : "badge badge-dim"}>agent={String(Boolean(tool.exposure?.agent))}</span>
            <span className={tool.dynamic ? "badge badge-emerald" : "badge badge-dim"}>registered={String(tool.dynamic)}</span>
          </div>
        </div>

        <div className="detail-section">
          <div className="field-label mb-sm">Scopes</div>
          <div className="badge-row">
            {(tool.required_scopes?.length ? tool.required_scopes : ["none"]).map((scope) => (
              <span key={scope} className="badge badge-amber">{scope}</span>
            ))}
          </div>
        </div>

        <div className="detail-section">
          <div className="field-label mb-sm">Input Schema</div>
          <div className="schema-grid">
            {inputProperties.length > 0 ? inputProperties.map((name) => (
              <div key={name} className="schema-chip">
                <span className="mono">{name}</span>
                {required.includes(name) && <span className="badge badge-coral">required</span>}
              </div>
            )) : (
              <span className="muted">empty</span>
            )}
          </div>
        </div>

        <div className="detail-section">
          <div className="field-label mb-sm">Sensitive Fields</div>
          <div className="badge-row">
            {(tool.sensitive_fields?.length ? tool.sensitive_fields : ["none"]).map((field) => (
              <span key={field} className="badge badge-dim">{field}</span>
            ))}
          </div>
        </div>

        <div className="detail-section">
          <div className="field-label mb-sm">Approval</div>
          <pre className="json-preview">{JSON.stringify(tool.approval ?? {}, null, 2)}</pre>
        </div>
      </div>
    </div>
  );
}

function Field({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="detail-field">
      <div className="field-label">{label}</div>
      <div className={mono ? "mono detail-value" : "detail-value"}>{value}</div>
    </div>
  );
}

function StatusBadge({ tool }: { tool: ToolRow }) {
  if (tool.status === "approved") return <span className="badge badge-emerald">approved</span>;
  if (tool.status === "rejected") return <span className="badge badge-coral">rejected</span>;
  return <span className="badge badge-warn">{tool.status ?? "pending"}</span>;
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
