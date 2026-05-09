import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useApp } from "../context/AppContext";
import { useInvestigation } from "../context/InvestigationContext";
import { usePolling } from "../hooks/usePolling";
import { atlas, lens, probe, type AtlasStatus, type LogItem, type ServiceInfo } from "../api/client";
import { formatLogTime } from "../utils/time";
import { serviceDatabases, serviceSourceLabel, serviceStatusBadge, serviceStatusLabel } from "../utils/serviceLabels";

const SVC = {
  atlas: { port: 3001, desc: "元数据中心 — Schema 管理与服务注册" },
  probe: { port: 3002, desc: "日志观测 — 日志搜索与链路追踪" },
  lens: { port: 3003, desc: "数据查询 — 业务实体映射与 DSL" },
} as const;

export default function Dashboard() {
  const { configLoaded, demoMode } = useApp();
  if (!configLoaded) return <LoadingDashboard />;
  if (demoMode) return <DemoDashboard />;
  return <FullDashboard />;
}

function LoadingDashboard() {
  return (
    <>
      <div className="page-header">
        <h2>概览</h2>
        <div className="page-desc">Meridian 运维观测平台</div>
      </div>
      <div className="page-body">
        <div className="empty">
          <div className="empty-text">正在加载运行配置</div>
        </div>
      </div>
    </>
  );
}

function DemoDashboard() {
  const navigate = useNavigate();
  return (
    <>
      <div className="page-header">
        <h2>概览</h2>
        <div className="page-desc">Meridian 演示入口 — 已隐藏数据库、日志和内部元数据</div>
      </div>
      <div className="page-body">
        <div className="g3 mb-md">
          <div className="svc-card online fade-up stagger-1" onClick={() => navigate("/chat")}>
            <div className="svc-head">
              <span className="svc-name">Agent</span>
              <span className="svc-port">demo</span>
            </div>
            <div className="svc-desc">只展示 Meridian 的诊断交互入口，不暴露真实日志和业务库。</div>
            <div className="svc-status">
              <span className="status-dot online" />
              <span style={{ color: "var(--emerald)" }}>可访问</span>
            </div>
          </div>
          <div className="svc-card checking fade-up stagger-2">
            <div className="svc-head">
              <span className="svc-name">Evidence</span>
              <span className="svc-port">masked</span>
            </div>
            <div className="svc-desc">Atlas、Lens、Probe 的原始数据页面和 API 已在演示模式下关闭。</div>
            <div className="svc-status">
              <span className="status-dot checking" />
              <span style={{ color: "var(--warn)" }}>受保护</span>
            </div>
          </div>
          <div className="svc-card online fade-up stagger-3">
            <div className="svc-head">
              <span className="svc-name">Nexus</span>
              <span className="svc-port">gateway</span>
            </div>
            <div className="svc-desc">公网展示只经过登录门禁和演示白名单，内部服务不直接开放。</div>
            <div className="svc-status">
              <span className="status-dot online" />
              <span style={{ color: "var(--emerald)" }}>已启用</span>
            </div>
          </div>
        </div>

        <div className="card fade-up stagger-4">
          <div className="card-head">
            <h3>演示范围</h3>
            <button className="btn btn-primary btn-sm" onClick={() => navigate("/chat")}>
              打开 Agent
            </button>
          </div>
          <div className="card-body">
            <div className="row gap-sm wrap">
              <span className="badge badge-emerald">登录访问</span>
              <span className="badge badge-teal">Chat only</span>
              <span className="badge badge-warn">日志隐藏</span>
              <span className="badge badge-warn">数据库隐藏</span>
              <span className="badge badge-dim">MCP/Registry hidden</span>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}

function FullDashboard() {
  const { health } = useApp();
  const inv = useInvestigation();
  const navigate = useNavigate();

  const [atlasStatus, setAtlasStatus] = useState<AtlasStatus | null>(null);
  const [services, setServices] = useState<ServiceInfo[]>([]);
  const [entityCount, setEntityCount] = useState<number | null>(null);

  // Live error feed — polls every 15s
  const prevErrorCount = useRef(0);
  const { data: errorData } = usePolling(
    () => probe.tailErrors(1, 20),
    15000
  );
  const recentErrors = errorData?.items ?? [];
  const newErrorCount = recentErrors.length - prevErrorCount.current;
  useEffect(() => { prevErrorCount.current = recentErrors.length; }, [recentErrors.length]);

  useEffect(() => {
    atlas.status().then(setAtlasStatus).catch(() => {});
    atlas.listServices().then((r) => setServices(r.service)).catch(() => {});
    lens.status().then((r) => setEntityCount(r.entities.cached_count)).catch(() => {});
  }, []);

  const onlineCount = Object.values(health).filter((s) => s === "online").length;

  function handleErrorClick(item: LogItem) {
    if (item.request_id) {
      inv.push({
        type: "error",
        label: `ERR ${item.request_id.slice(0, 12)}...`,
        path: `/probe?tab=trace&rid=${item.request_id}`,
        data: { request_id: item.request_id },
      });
    } else {
      navigate("/probe?tab=errors");
    }
  }

  return (
    <>
      <div className="page-header">
        <h2>概览</h2>
        <div className="page-desc">Meridian 运维观测平台 — 系统概览</div>
      </div>

      <div className="page-body">
        {/* Service health cards */}
        <div className="g3 mb-md">
          {(["atlas", "probe", "lens"] as const).map((name, i) => (
            <div
              key={name}
              className={`svc-card ${health[name]} fade-up stagger-${i + 1}`}
              onClick={() => navigate(`/${name}`)}
            >
              <div className="svc-head">
                <span className="svc-name">{name.charAt(0).toUpperCase() + name.slice(1)}</span>
                <span className="svc-port">:{SVC[name].port}</span>
              </div>
              <div className="svc-desc">{SVC[name].desc}</div>
              <div className="svc-status">
                <span className={`status-dot ${health[name]}`} />
                <span style={{ color: health[name] === "online" ? "var(--emerald)" : health[name] === "offline" ? "var(--coral)" : "var(--warn)" }}>
                  {health[name] === "online" ? "在线" : health[name] === "checking" ? "检查中" : "离线"}
                </span>
              </div>
            </div>
          ))}
        </div>

        {/* Stats */}
        <div className="g4 mb-md">
          <div className="card fade-up stagger-2">
            <div className="stat">
              <div className={`stat-val ${onlineCount === 3 ? "emerald" : onlineCount > 0 ? "amber" : "coral"}`}>
                {onlineCount}/3
              </div>
              <div className="stat-label">在线服务</div>
            </div>
          </div>
          <div className="card fade-up stagger-3">
            <div className="stat">
              <div className="stat-val teal">{atlasStatus?.total_databases ?? "\u2014"}</div>
              <div className="stat-label">已跟踪数据库</div>
            </div>
          </div>
          <div className="card fade-up stagger-4">
            <div className="stat">
              <div className="stat-val amber">{services.length || "\u2014"}</div>
              <div className="stat-label">已发现服务</div>
            </div>
          </div>
          <div className="card fade-up stagger-5">
            <div className="stat">
              <div className="stat-val violet">{entityCount ?? "\u2014"}</div>
              <div className="stat-label">业务实体</div>
            </div>
          </div>
        </div>

        <div className="g2">
          {/* Live error feed */}
          <div className="card fade-up stagger-4">
            <div className="card-head">
              <h3>
                实时错误
                {newErrorCount > 0 && (
                  <span className="badge badge-coral" style={{ marginLeft: 8 }}>新增 {newErrorCount}</span>
                )}
              </h3>
              <button className="btn btn-ghost btn-sm" onClick={() => navigate("/probe?tab=errors")}>
                查看全部
              </button>
            </div>
            <div className="card-body flush" style={{ maxHeight: 320, overflowY: "auto" }}>
              {recentErrors.length > 0 ? (
                recentErrors.slice(0, 15).map((item, i) => (
                  <div
                    key={i}
                    className={`log-line clickable ${i < newErrorCount ? "new-item" : ""}`}
                    onClick={() => handleErrorClick(item)}
                  >
                    <span className="log-ts">{formatLogTime(item.timestamp)}</span>
                    <span className={`log-level ${item.level}`}>{item.level}</span>
                    {item.source && <span className="log-svc">[{item.source}]</span>}
                    <span className="log-msg">{item.text}</span>
                  </div>
                ))
              ) : (
                <div className="empty">
                  <div className="empty-icon">{"\u2713"}</div>
                  <div className="empty-text">最近没有错误</div>
                </div>
              )}
            </div>
          </div>

          {/* Connections & schemas */}
          <div className="card fade-up stagger-5">
            <div className="card-head">
              <h3>数据库连接</h3>
              <button className="btn btn-ghost btn-sm" onClick={() => navigate("/atlas")}>
                Atlas
              </button>
            </div>
            <div className="card-body">
              {atlasStatus ? (
                <>
                  {Object.entries(atlasStatus.connections).map(([db, st]) => (
                    <div key={db} className="flex-between mb-sm">
                      <span style={{ fontFamily: "var(--font-mono)", fontSize: 12 }}>{db}</span>
                      <span className={`badge ${st.includes("disconnected") ? "badge-coral" : "badge-emerald"}`}>
                        {st}
                      </span>
                    </div>
                  ))}
                  {Object.keys(atlasStatus.databases).length > 0 && (
                    <div className="mt-md">
                      <div style={{ fontSize: 10, color: "var(--t4)", fontFamily: "var(--font-display)", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 6 }}>
                        Schema
                      </div>
                      {Object.entries(atlasStatus.databases).map(([db, info]) => (
                        <div
                          key={db}
                          className="flex-between mb-sm"
                          style={{ cursor: "pointer" }}
                          onClick={() => {
                            inv.push({
                              type: "schema",
                              label: db,
                              path: `/atlas?tab=schemas&db=${db}`,
                              data: { database: db },
                            });
                          }}
                        >
                          <span style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--teal)" }}>
                            {db}
                          </span>
                          <span className="badge badge-dim">{info.table_count} 张表</span>
                        </div>
                      ))}
                    </div>
                  )}
                </>
              ) : (
                <div className="empty">
                  <div className="empty-text">Atlas 离线</div>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Discovered services */}
        {services.length > 0 && (
          <div className="card mt-lg fade-up stagger-6">
            <div className="card-head">
              <h3>已发现服务</h3>
              <span className="badge badge-teal">{services.length}</span>
            </div>
            <div className="card-body flush" style={{ overflowX: "auto" }}>
              <table className="dtable">
                <thead>
                  <tr>
                    <th>名称</th>
                    <th>状态</th>
                    <th>来源</th>
                    <th>PID</th>
                    <th>路径</th>
                    <th>数据库</th>
                  </tr>
                </thead>
                <tbody>
                  {services.map((svc) => (
                    <tr key={svc.name}>
                      <td
                        className="mono link"
                        onClick={() =>
                          inv.push({
                            type: "service",
                            label: svc.name,
                            path: `/probe?tab=service&svc=${svc.name}`,
                            data: { service: svc.name },
                          })
                        }
                      >
                        {svc.name}
                      </td>
                      <td>
                        <span className={`badge ${serviceStatusBadge(svc.status)}`}>
                          {serviceStatusLabel(svc.status)}
                        </span>
                      </td>
                      <td><span className="badge badge-dim">{serviceSourceLabel(svc.source)}</span></td>
                      <td className="mono">{svc.pid || "\u2014"}</td>
                      <td className="mono truncate" style={{ maxWidth: 200, fontSize: 11 }}>
                        {svc.deploy_path || "\u2014"}
                      </td>
                      <td>
                        <div className="row gap-xs wrap">
                          {serviceDatabases(svc).length > 0
                            ? serviceDatabases(svc).map((d) => (
                              <span key={d} className="badge badge-dim">{d}</span>
                            ))
                            : "\u2014"}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </>
  );
}
