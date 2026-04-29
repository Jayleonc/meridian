import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useApp } from "../../context/AppContext";
import { useInvestigation } from "../../context/InvestigationContext";
import { usePolling } from "../../hooks/usePolling";
import { probe, type LogContext, type LogItem, type SearchResult, type TraceSummary } from "../../api/client";
import { formatLogTime } from "../../utils/time";

type Tab = "errors" | "search" | "trace";

export default function ProbePage() {
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") as Tab) || "errors";
  const { toast } = useApp();
  const inv = useInvestigation();

  function setTab(t: Tab) {
    setParams({ tab: t });
  }

  // ── Error feed (live polling) ──
  const [hoursBack, setHoursBack] = useState(1);
  const [errorLimit, setErrorLimit] = useState(200);
  const prevIds = useRef<Set<string>>(new Set());

  const errorFetcher = useCallback(
    () => probe.tailErrors(hoursBack, errorLimit, true),
    [hoursBack, errorLimit]
  );
  const { data: errorData, loading: errorLoading } = usePolling(
    errorFetcher, tab === "errors" ? 10000 : 0, [hoursBack, errorLimit]
  );

  // Track new items for animation
  const [newItemIds, setNewItemIds] = useState<Set<number>>(new Set());
  useEffect(() => {
    if (!errorData) return;
    const fresh = new Set<number>();
    errorData.items.forEach((item, i) => {
      const key = `${item.timestamp}:${item.text?.slice(0, 40)}`;
      if (!prevIds.current.has(key)) fresh.add(i);
    });
    if (fresh.size > 0 && prevIds.current.size > 0) {
      setNewItemIds(fresh);
      setTimeout(() => setNewItemIds(new Set()), 1200);
    }
    const nextSet = new Set<string>();
    errorData.items.forEach((item) => {
      nextSet.add(`${item.timestamp}:${item.text?.slice(0, 40)}`);
    });
    prevIds.current = nextSet;
  }, [errorData]);

  // ── Search ──
  const [keyword, setKeyword] = useState("");
  const [level, setLevel] = useState("");
  const [searchLimit, setSearchLimit] = useState(200);
  const [searchResult, setSearchResult] = useState<SearchResult | null>(null);
  const [searchLoading, setSearchLoading] = useState(false);

  async function handleSearch() {
    if (!keyword.trim()) return;
    setSearchLoading(true);
    try {
      const r = await probe.search({
        keyword: keyword.trim(),
        level: level || undefined,
        limit: searchLimit,
        include_full: true,
      });
      setSearchResult(r);
    } catch (e) {
      toast("error", e instanceof Error ? e.message : "搜索失败");
    }
    setSearchLoading(false);
  }

  // ── Trace ──
  const initRid = params.get("rid") || "";
  const [requestId, setRequestId] = useState(initRid);
  const [backHours, setBackHours] = useState(0);
  const [traceResult, setTraceResult] = useState<TraceSummary | null>(null);
  const [traceLoading, setTraceLoading] = useState(false);

  // Auto-trace if rid is in URL
  useEffect(() => {
    if (initRid && tab === "trace") {
      setRequestId(initRid);
      doTrace(initRid);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initRid]);

  async function doTrace(rid?: string) {
    const id = (rid || requestId).trim();
    if (!id) return;
    setTraceLoading(true);
    try {
      const r = await probe.trace(id, backHours);
      setTraceResult(r);
    } catch (e) {
      toast("error", e instanceof Error ? e.message : "链路查询失败");
    }
    setTraceLoading(false);
  }

  // ── Log context + copy ──
  const [contextTarget, setContextTarget] = useState<LogItem | null>(null);
  const [contextData, setContextData] = useState<LogContext | null>(null);
  const [contextLoading, setContextLoading] = useState(false);

  async function copyText(text: string, label: string) {
    try {
      await navigator.clipboard.writeText(text);
      toast("success", `已复制${label}`);
    } catch {
      toast("error", "复制失败，浏览器没有开放剪贴板权限");
    }
  }

  function formatLogItem(item: LogItem) {
    const parts = [
      item.timestamp,
      item.level,
      item.request_id ? `<${item.request_id}>` : "",
      item.source ? `[${item.source}]` : "",
      item.file && item.line_number ? `${item.file}:${item.line_number}` : "",
      item.text,
    ].filter(Boolean);
    return parts.join(" ");
  }

  function formatContext(data: LogContext) {
    const start = data.line_number - data.context.before.length;
    const before = data.context.before.map((line, i) => `${start + i}: ${line}`);
    const match = [`${data.line_number}: ${data.context.match}`];
    const after = data.context.after.map((line, i) => `${data.line_number + i + 1}: ${line}`);
    return [`# ${data.file}`, ...before, ...match, ...after].join("\n");
  }

  function copyLogs(result: SearchResult | null, label: string) {
    const lines = result?.items.map(formatLogItem) ?? [];
    if (lines.length === 0) return;
    void copyText(lines.join("\n"), label);
  }

  async function openContext(item: LogItem) {
    if (!item.file || !item.line_number) {
      toast("info", "这条日志没有文件行号，无法读取上下文");
      return;
    }
    setContextTarget(item);
    setContextData(null);
    setContextLoading(true);
    try {
      const data = await probe.context(item.file, item.line_number, 20, 20);
      setContextData(data);
    } catch (e) {
      toast("error", e instanceof Error ? e.message : "上下文读取失败");
    } finally {
      setContextLoading(false);
    }
  }

  function traceLog(item: LogItem) {
    if (item.request_id) {
      inv.push({
        type: "trace",
        label: item.request_id.slice(0, 16),
        path: `/probe?tab=trace&rid=${item.request_id}`,
        data: { request_id: item.request_id },
      });
    }
  }

  function onTraceServiceClick(svc: string) {
    inv.push({
      type: "service",
      label: svc,
      path: `/atlas?tab=services&svc=${svc}`,
      data: { service: svc },
    });
  }

  return (
    <>
      <div className="page-header">
        <div className="flex-between">
          <div>
            <h2>Probe</h2>
            <div className="page-desc">日志观测 — 搜索、巡检、链路追踪</div>
          </div>
        </div>
        <div className="page-toolbar">
          <div className="tab-bar">
            <button className={`tab-btn ${tab === "errors" ? "active" : ""}`} onClick={() => setTab("errors")}>
              实时错误
              {errorData && errorData.summary.total_matches > 0 && (
                <span className="tab-count">{errorData.summary.total_matches}</span>
              )}
            </button>
            <button className={`tab-btn ${tab === "search" ? "active" : ""}`} onClick={() => setTab("search")}>
              日志搜索
            </button>
            <button className={`tab-btn ${tab === "trace" ? "active" : ""}`} onClick={() => setTab("trace")}>
              请求链路
            </button>
          </div>
        </div>
      </div>

      <div className="page-body">
        {/* ════ ERRORS TAB ════ */}
        {tab === "errors" && (
          <div className="fade-up">
            <div className="row gap-sm mb-md">
              <select className="input" style={{ width: 140 }} value={hoursBack} onChange={(e) => setHoursBack(Number(e.target.value))}>
                {[1, 2, 4, 8, 12, 24].map((h) => <option key={h} value={h}>最近 {h} 小时</option>)}
              </select>
              <select className="input" style={{ width: 130 }} value={errorLimit} onChange={(e) => setErrorLimit(Number(e.target.value))}>
                {[50, 100, 200, 500].map((n) => <option key={n} value={n}>最新 {n} 条</option>)}
              </select>
              <button className="btn btn-ghost btn-sm" onClick={() => copyLogs(errorData ?? null, "错误日志")} disabled={!errorData?.items.length}>
                复制日志
              </button>
              {errorLoading && <span className="badge badge-amber"><span className="spinner" /> 刷新中</span>}
              {errorData && (
                <>
                  <span className="badge badge-coral">显示 {errorData.summary.returned} 条</span>
                  {errorData.summary.time_range?.start && (
                    <span className="badge badge-teal">
                      {formatLogTime(errorData.summary.time_range.start)} - {formatLogTime(errorData.summary.time_range.end)}
                    </span>
                  )}
                  {errorData.summary.truncated && <span className="badge badge-warn">已到返回上限</span>}
                </>
              )}
            </div>

            <div className="card">
              <div className="card-body flush" style={{ maxHeight: "calc(100vh - 260px)", overflowY: "auto" }}>
                {(errorData?.items ?? []).length > 0 ? (
                  (errorData?.items ?? []).map((item, i) => (
                    <LogLineView
                      key={i}
                      item={item}
                      isNew={newItemIds.has(i)}
                      onOpenContext={openContext}
                      onTrace={traceLog}
                      onCopy={(target) => copyText(formatLogItem(target), "单条日志")}
                    />
                  ))
                ) : (
                  <div className="empty">
                    <div className="empty-icon">{"\u2713"}</div>
                    <div className="empty-text">{errorLoading ? "加载中..." : "这个时间范围没有错误日志"}</div>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

        {/* ════ SEARCH TAB ════ */}
        {tab === "search" && (
          <div className="fade-up">
            <div className="row gap-sm mb-md">
              <input
                className="input"
                style={{ flex: 1 }}
                placeholder="输入关键词，例如 timeout、request_id、服务名"
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleSearch()}
                autoFocus
              />
              <select className="input" style={{ width: 120 }} value={level} onChange={(e) => setLevel(e.target.value)}>
                <option value="">全部级别</option>
                <option value="ERR">ERR</option>
                <option value="WAR">WAR</option>
                <option value="INF">INF</option>
                <option value="DBG">DBG</option>
              </select>
              <select className="input" style={{ width: 130 }} value={searchLimit} onChange={(e) => setSearchLimit(Number(e.target.value))}>
                {[50, 100, 200, 500].map((n) => <option key={n} value={n}>返回 {n} 条</option>)}
              </select>
              <button className="btn btn-primary" onClick={handleSearch} disabled={searchLoading || !keyword.trim()}>
                {searchLoading ? <><span className="spinner" /> 搜索中</> : "搜索"}
              </button>
            </div>

            {searchResult && (
              <>
                <div className="row gap-sm mb-md">
                  <span className="badge badge-teal">命中 {searchResult.summary.total_matches} 条</span>
                  <button className="btn btn-ghost btn-sm" onClick={() => copyLogs(searchResult, "搜索结果")} disabled={!searchResult.items.length}>
                    复制结果
                  </button>
                  {searchResult.summary.truncated && <span className="badge badge-warn">已到返回上限</span>}
                </div>

                <div className="card">
                  <div className="card-body flush" style={{ maxHeight: "calc(100vh - 300px)", overflowY: "auto" }}>
                    {searchResult.items.map((item, i) => (
                      <LogLineView
                        key={i}
                        item={item}
                        onOpenContext={openContext}
                        onTrace={traceLog}
                        onCopy={(target) => copyText(formatLogItem(target), "单条日志")}
                      />
                    ))}
                  </div>
                </div>
              </>
            )}
          </div>
        )}

        {/* ════ TRACE TAB ════ */}
        {tab === "trace" && (
          <div className="fade-up">
            <div className="row gap-sm mb-md">
              <input
                className="input"
                style={{ flex: 1 }}
                placeholder="输入 request_id"
                value={requestId}
                onChange={(e) => setRequestId(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && doTrace()}
                autoFocus
              />
              <select className="input" style={{ width: 140 }} value={backHours} onChange={(e) => setBackHours(Number(e.target.value))}>
                <option value={0}>当前小时</option>
                {[1, 2, 4, 8, 12, 24, 48].map((h) => <option key={h} value={h}>回看 {h} 小时</option>)}
              </select>
              <button className="btn btn-primary" onClick={() => doTrace()} disabled={traceLoading || !requestId.trim()}>
                {traceLoading ? <><span className="spinner" /> 查询中</> : "查询链路"}
              </button>
            </div>

            {traceResult && <TraceView trace={traceResult} onServiceClick={onTraceServiceClick} />}
          </div>
        )}

        {contextTarget && (
          <LogContextPanel
            item={contextTarget}
            data={contextData}
            loading={contextLoading}
            onClose={() => {
              setContextTarget(null);
              setContextData(null);
            }}
            onCopy={() => {
              if (contextData) void copyText(formatContext(contextData), "上下文");
            }}
          />
        )}
      </div>
    </>
  );
}

/* ════════════════════════════════════════════
   Log Viewer
   ════════════════════════════════════════════ */

function LogLineView({
  item,
  isNew = false,
  onOpenContext,
  onTrace,
  onCopy,
}: {
  item: LogItem;
  isNew?: boolean;
  onOpenContext: (item: LogItem) => void;
  onTrace: (item: LogItem) => void;
  onCopy: (item: LogItem) => void;
}) {
  return (
    <div
      className={`log-line log-line-expanded ${isNew ? "new-item" : ""}`}
      onClick={() => onOpenContext(item)}
      title={item.file && item.line_number ? `${item.file}:${item.line_number}` : undefined}
    >
      <span className="log-ts">{formatLogTime(item.timestamp)}</span>
      <span className={`log-level ${item.level}`}>{item.level || "--"}</span>
      {item.source && <span className="log-svc">[{item.source}]</span>}
      <span className="log-msg">{item.text}</span>
      <span className="log-actions">
        {item.request_id && (
          <button
            type="button"
            className="btn btn-ghost btn-sm log-action"
            onClick={(event) => {
              event.stopPropagation();
              onTrace(item);
            }}
            title={item.request_id}
          >
            追踪
          </button>
        )}
        <button
          type="button"
          className="btn btn-ghost btn-sm log-action"
          onClick={(event) => {
            event.stopPropagation();
            onCopy(item);
          }}
        >
          复制
        </button>
      </span>
    </div>
  );
}

function LogContextPanel({
  item,
  data,
  loading,
  onClose,
  onCopy,
}: {
  item: LogItem;
  data: LogContext | null;
  loading: boolean;
  onClose: () => void;
  onCopy: () => void;
}) {
  const start = data ? data.line_number - data.context.before.length : 0;
  return (
    <div className="card log-context-panel fade-up">
      <div className="card-head">
        <div>
          <h3>日志上下文</h3>
          <div className="log-context-source">
            {item.file && item.line_number ? `${item.file}:${item.line_number}` : "无文件位置"}
          </div>
        </div>
        <div className="row gap-sm">
          <button className="btn btn-ghost btn-sm" onClick={onCopy} disabled={!data}>复制上下文</button>
          <button className="btn btn-ghost btn-sm" onClick={onClose}>关闭</button>
        </div>
      </div>
      <div className="card-body flush">
        {loading && (
          <div className="empty" style={{ padding: 20 }}>
            <div className="empty-text"><span className="spinner" /> 正在读取上下文</div>
          </div>
        )}
        {!loading && data && (
          <div className="log-context-lines">
            {data.context.before.map((line, i) => (
              <div key={`b-${i}`} className="log-context-line">
                <span>{start + i}</span>
                <code>{line}</code>
              </div>
            ))}
            <div className="log-context-line match">
              <span>{data.line_number}</span>
              <code>{data.context.match}</code>
            </div>
            {data.context.after.map((line, i) => (
              <div key={`a-${i}`} className="log-context-line">
                <span>{data.line_number + i + 1}</span>
                <code>{line}</code>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

/* ════════════════════════════════════════════
   Trace Visualization (inline)
   ════════════════════════════════════════════ */

function TraceView({
  trace,
  onServiceClick,
}: {
  trace: TraceSummary;
  onServiceClick: (svc: string) => void;
}) {
  return (
    <div className="fade-up">
      {/* Stats row */}
      <div className="g4 mb-md">
        <div className="card">
          <div className="stat">
            <div className="stat-val teal">{trace.total_lines}</div>
            <div className="stat-label">日志行数</div>
          </div>
        </div>
        <div className="card">
          <div className="stat">
            <div className="stat-val violet">{trace.services.length}</div>
            <div className="stat-label">服务数</div>
          </div>
        </div>
        <div className="card">
          <div className="stat">
            <div className="stat-val coral">{trace.error_count}</div>
            <div className="stat-label">错误数</div>
          </div>
        </div>
        <div className="card">
          <div className="stat">
            <div className="stat-val amber">{trace.warn_count}</div>
            <div className="stat-label">警告数</div>
          </div>
        </div>
      </div>

      {/* Request path — clickable services */}
      <div className="card mb-md">
        <div className="card-head">
          <h3>请求路径</h3>
          <span style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--t4)" }}>
            {trace.time_range}
          </span>
        </div>
        <div className="card-body">
          <div className="row gap-sm wrap">
            {trace.services.map((svc, i) => (
              <span key={svc} className="row gap-sm">
                <span
                  className="badge badge-teal"
                  style={{ cursor: "pointer" }}
                  onClick={() => onServiceClick(svc)}
                  title={`在 Atlas 中查看 ${svc}`}
                >
                  {svc}
                </span>
                {i < trace.services.length - 1 && (
                  <span style={{ color: "var(--t4)", fontSize: 11 }}>{"\u2192"}</span>
                )}
              </span>
            ))}
          </div>
        </div>
      </div>

      {/* Hint */}
      {trace.hint && (
        <div className="card mb-md" style={{ borderLeftColor: "var(--warn)", borderLeftWidth: 3 }}>
          <div className="card-body" style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--warn)", lineHeight: 1.6 }}>
            {trace.hint}
          </div>
        </div>
      )}

      {/* Errors */}
      {trace.errors.length > 0 && (
        <div className="card mb-md" style={{ borderLeftColor: "var(--coral)", borderLeftWidth: 3 }}>
          <div className="card-head">
            <h3 style={{ color: "var(--coral)" }}>错误日志 ({trace.error_count})</h3>
          </div>
          <div className="card-body flush" style={{ maxHeight: 280, overflowY: "auto" }}>
            {trace.errors.map((e, i) => (
              <div key={i} className="log-line">
                <span className="log-ts">{formatLogTime(e.timestamp)}</span>
                <span className="log-level ERR">ERR</span>
                <span className="log-svc" style={{ cursor: "pointer" }} onClick={() => onServiceClick(e.service)}>
                  [{e.service}]
                </span>
                <span className="log-msg">{e.message}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Warnings */}
      {trace.warns.length > 0 && (
        <div className="card mb-md" style={{ borderLeftColor: "var(--warn)", borderLeftWidth: 3 }}>
          <div className="card-head">
            <h3 style={{ color: "var(--warn)" }}>警告日志 ({trace.warn_count})</h3>
          </div>
          <div className="card-body flush" style={{ maxHeight: 200, overflowY: "auto" }}>
            {trace.warns.map((w, i) => (
              <div key={i} className="log-line">
                <span className="log-ts">{formatLogTime(w.timestamp)}</span>
                <span className="log-level WAR">WAR</span>
                <span className="log-svc">[{w.service}]</span>
                <span className="log-msg">{w.message}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Timeline */}
      {trace.timeline.length > 0 && (
        <div className="card">
          <div className="card-head">
            <h3>时间线 ({trace.timeline.length})</h3>
          </div>
          <div className="card-body flush" style={{ maxHeight: 400, overflowY: "auto" }}>
            {trace.timeline.map((t, i) => (
              <div key={i} className="log-line">
                <span className="log-ts">{formatLogTime(t.timestamp)}</span>
                <span className={`log-level ${t.level}`}>{t.level}</span>
                <span className="log-svc" style={{ cursor: "pointer" }} onClick={() => onServiceClick(t.service)}>
                  [{t.service}]
                </span>
                <span className="log-msg">{t.message}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
