import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useApp } from "../../context/AppContext";
import { useInvestigation } from "../../context/InvestigationContext";
import { usePolling } from "../../hooks/usePolling";
import { probe, type LogItem, type SearchResult, type TraceSummary } from "../../api/client";
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
  const prevIds = useRef<Set<string>>(new Set());

  const errorFetcher = useCallback(
    () => probe.tailErrors(hoursBack, 50),
    [hoursBack]
  );
  const { data: errorData, loading: errorLoading } = usePolling(
    errorFetcher, tab === "errors" ? 10000 : 0, [hoursBack]
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
  const [searchResult, setSearchResult] = useState<SearchResult | null>(null);
  const [searchLoading, setSearchLoading] = useState(false);

  async function handleSearch() {
    if (!keyword.trim()) return;
    setSearchLoading(true);
    try {
      const r = await probe.search({ keyword: keyword.trim(), level: level || undefined, limit: 50 });
      setSearchResult(r);
    } catch (e) {
      toast("error", e instanceof Error ? e.message : "Search failed");
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
      toast("error", e instanceof Error ? e.message : "Trace failed");
    }
    setTraceLoading(false);
  }

  // ── Clickable log item ──
  function onLogClick(item: LogItem) {
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
              Live Errors
              {errorData && errorData.summary.total_matches > 0 && (
                <span className="tab-count">{errorData.summary.total_matches}</span>
              )}
            </button>
            <button className={`tab-btn ${tab === "search" ? "active" : ""}`} onClick={() => setTab("search")}>
              Search
            </button>
            <button className={`tab-btn ${tab === "trace" ? "active" : ""}`} onClick={() => setTab("trace")}>
              Trace
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
                {[1, 2, 4, 8, 12, 24].map((h) => <option key={h} value={h}>Past {h}h</option>)}
              </select>
              {errorLoading && <span className="badge badge-amber"><span className="spinner" /> Polling...</span>}
              {errorData && (
                <span className="badge badge-coral">{errorData.summary.total_matches} errors</span>
              )}
            </div>

            <div className="card">
              <div className="card-body flush" style={{ maxHeight: "calc(100vh - 260px)", overflowY: "auto" }}>
                {(errorData?.items ?? []).length > 0 ? (
                  (errorData?.items ?? []).map((item, i) => (
                    <div
                      key={i}
                      className={`log-line ${item.request_id ? "clickable" : ""} ${newItemIds.has(i) ? "new-item" : ""}`}
                      onClick={() => onLogClick(item)}
                      title={item.request_id ? `Click to trace ${item.request_id}` : undefined}
                    >
                      <span className="log-ts">{formatLogTime(item.timestamp)}</span>
                      <span className={`log-level ${item.level}`}>{item.level}</span>
                      {item.source && <span className="log-svc">[{item.source}]</span>}
                      <span className="log-msg">{item.text}</span>
                      {item.request_id && (
                        <span style={{ color: "var(--t4)", fontSize: 10, marginLeft: "auto", flexShrink: 0 }}>
                          {item.request_id.slice(0, 12)}
                        </span>
                      )}
                    </div>
                  ))
                ) : (
                  <div className="empty">
                    <div className="empty-icon">{"\u2713"}</div>
                    <div className="empty-text">{errorLoading ? "Loading..." : "No errors in this time range"}</div>
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
                placeholder="keyword..."
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleSearch()}
                autoFocus
              />
              <select className="input" style={{ width: 120 }} value={level} onChange={(e) => setLevel(e.target.value)}>
                <option value="">All Levels</option>
                <option value="ERR">ERR</option>
                <option value="WAR">WAR</option>
                <option value="INF">INF</option>
                <option value="DBG">DBG</option>
              </select>
              <button className="btn btn-primary" onClick={handleSearch} disabled={searchLoading || !keyword.trim()}>
                {searchLoading ? <><span className="spinner" /> Searching</> : "Search"}
              </button>
            </div>

            {searchResult && (
              <>
                <div className="row gap-sm mb-md">
                  <span className="badge badge-teal">{searchResult.summary.total_matches} matches</span>
                  {searchResult.summary.truncated && <span className="badge badge-warn">truncated</span>}
                </div>

                <div className="card">
                  <div className="card-body flush" style={{ maxHeight: "calc(100vh - 300px)", overflowY: "auto" }}>
                    {searchResult.items.map((item, i) => (
                      <div
                        key={i}
                        className={`log-line ${item.request_id ? "clickable" : ""}`}
                        onClick={() => onLogClick(item)}
                      >
                        <span className="log-ts">{formatLogTime(item.timestamp)}</span>
                        <span className={`log-level ${item.level}`}>{item.level}</span>
                        {item.source && <span className="log-svc">[{item.source}]</span>}
                        <span className="log-msg">{item.text}</span>
                      </div>
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
                placeholder="request_id..."
                value={requestId}
                onChange={(e) => setRequestId(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && doTrace()}
                autoFocus
              />
              <select className="input" style={{ width: 140 }} value={backHours} onChange={(e) => setBackHours(Number(e.target.value))}>
                <option value={0}>Current hour</option>
                {[1, 2, 4, 8, 12, 24, 48].map((h) => <option key={h} value={h}>Back {h}h</option>)}
              </select>
              <button className="btn btn-primary" onClick={() => doTrace()} disabled={traceLoading || !requestId.trim()}>
                {traceLoading ? <><span className="spinner" /> Tracing</> : "Trace"}
              </button>
            </div>

            {traceResult && <TraceView trace={traceResult} onServiceClick={onTraceServiceClick} />}
          </div>
        )}
      </div>
    </>
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
            <div className="stat-label">Log Lines</div>
          </div>
        </div>
        <div className="card">
          <div className="stat">
            <div className="stat-val violet">{trace.services.length}</div>
            <div className="stat-label">Services</div>
          </div>
        </div>
        <div className="card">
          <div className="stat">
            <div className="stat-val coral">{trace.error_count}</div>
            <div className="stat-label">Errors</div>
          </div>
        </div>
        <div className="card">
          <div className="stat">
            <div className="stat-val amber">{trace.warn_count}</div>
            <div className="stat-label">Warnings</div>
          </div>
        </div>
      </div>

      {/* Request path — clickable services */}
      <div className="card mb-md">
        <div className="card-head">
          <h3>Request Path</h3>
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
                  title={`View ${svc} in Atlas`}
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
            <h3 style={{ color: "var(--coral)" }}>Errors ({trace.error_count})</h3>
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
            <h3 style={{ color: "var(--warn)" }}>Warnings ({trace.warn_count})</h3>
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
            <h3>Timeline ({trace.timeline.length})</h3>
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
