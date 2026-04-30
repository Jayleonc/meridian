import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useApp } from "../../context/AppContext";
import { useInvestigation } from "../../context/InvestigationContext";
import { usePolling } from "../../hooks/usePolling";
import { diagnosis, probe, type DiagnosisPack, type LogContext, type LogItem, type SearchResult, type TraceSummary } from "../../api/client";
import { formatLogTime } from "../../utils/time";
import { serviceSourceLabel } from "../../utils/serviceLabels";

type Tab = "errors" | "search" | "service" | "trace";
type LogSortOrder = "desc" | "asc";

const TRACE_BACK_OPTIONS = [0, 1, 2, 4, 8, 12, 24, 48, 72];
const TRACE_MAX_BACK_HOURS = 72;

function parseTraceTimestamp(timestamp?: string): Date | null {
  if (!timestamp) return null;
  const value = timestamp.trim();

  const brick = value.match(/^(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?/);
  if (brick) {
    const now = new Date();
    return new Date(
      now.getFullYear(),
      Number(brick[1]) - 1,
      Number(brick[2]),
      Number(brick[3]),
      Number(brick[4]),
      Number(brick[5] ?? 0)
    );
  }

  const iso = value.match(/^(\d{4})-(\d{2})-(\d{2})[T\s](\d{2}):(\d{2})(?::(\d{2}))?/);
  if (iso) {
    return new Date(
      Number(iso[1]),
      Number(iso[2]) - 1,
      Number(iso[3]),
      Number(iso[4]),
      Number(iso[5]),
      Number(iso[6] ?? 0)
    );
  }

  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? null : new Date(parsed);
}

function normalizeTraceHintTime(timestamp?: string): string {
  if (!timestamp) return "";
  const value = timestamp.trim();

  const brick = value.match(/^(\d{2}-\d{2}T\d{2}:\d{2})(?::(\d{2}))?/);
  if (brick) return `${brick[1]}:${brick[2] ?? "00"}`;

  const iso = value.match(/^(\d{4}-\d{2}-\d{2})[T\s](\d{2}:\d{2})(?::(\d{2}))?/);
  if (iso) return `${iso[1]}T${iso[2]}:${iso[3] ?? "00"}`;

  return value;
}

function traceBackHoursFromTimestamp(timestamp?: string): number {
  const target = parseTraceTimestamp(timestamp);
  if (!target) return 0;

  const now = new Date();
  const nowHour = new Date(now.getFullYear(), now.getMonth(), now.getDate(), now.getHours());
  const targetHour = new Date(
    target.getFullYear(),
    target.getMonth(),
    target.getDate(),
    target.getHours()
  );

  let diffMs = nowHour.getTime() - targetHour.getTime();
  if (diffMs < 0) diffMs += 24 * 60 * 60 * 1000;
  const hourBucketDiff = Math.floor(diffMs / (60 * 60 * 1000));
  return Math.min(TRACE_MAX_BACK_HOURS, Math.max(0, hourBucketDiff));
}

function traceBackHoursFromParams(backHoursParam: string | null, hintTime: string): number {
  if (backHoursParam !== null) {
    const parsed = Number(backHoursParam);
    if (Number.isFinite(parsed)) {
      return Math.min(TRACE_MAX_BACK_HOURS, Math.max(0, Math.floor(parsed)));
    }
  }
  return traceBackHoursFromTimestamp(hintTime);
}

function traceBackOptions(current: number) {
  if (TRACE_BACK_OPTIONS.includes(current)) return TRACE_BACK_OPTIONS;
  return [...TRACE_BACK_OPTIONS, current].sort((a, b) => a - b);
}

function traceBackOptionLabel(hours: number, auto: boolean) {
  if (hours === 0) return "当前小时";
  if (auto && !TRACE_BACK_OPTIONS.includes(hours)) return `自动回看 ${hours} 小时`;
  return `回看 ${hours} 小时`;
}

function traceAutoHintLabel(hintTime: string, backHours: number) {
  const target = parseTraceTimestamp(hintTime);
  if (!target) return `按日志时间 ${hintTime}`;

  let diffMs = Date.now() - target.getTime();
  if (diffMs < 0) diffMs += 24 * 60 * 60 * 1000;
  const diffMinutes = Math.max(0, Math.round(diffMs / (60 * 1000)));
  const age =
    diffMinutes < 90
      ? `约 ${Math.max(1, diffMinutes)} 分钟前`
      : `约 ${Math.max(1, Math.round(diffMinutes / 60))} 小时前`;
  const glogLabel = backHours > 0 ? `glog.sh -b ${backHours}` : "当前小时，无需 -b";
  return `${age}，${glogLabel}`;
}

function logItemFingerprint(item: LogItem) {
  return [
    item.timestamp,
    item.level,
    item.service || "",
    item.request_id || "",
    item.file || item.source || "",
    item.line_number || "",
    item.text?.slice(0, 120) || "",
  ].join(":");
}

function logTimestampMs(timestamp?: string) {
  if (!timestamp) return 0;

  const brick = timestamp.match(/^(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?/);
  if (brick) {
    const now = new Date();
    return new Date(
      now.getFullYear(),
      Number(brick[1]) - 1,
      Number(brick[2]),
      Number(brick[3]),
      Number(brick[4]),
      Number(brick[5] ?? 0)
    ).getTime();
  }

  const clockOnly = timestamp.match(/^(\d{2}):(\d{2})(?::(\d{2}))?/);
  if (clockOnly) {
    const now = new Date();
    return new Date(
      now.getFullYear(),
      now.getMonth(),
      now.getDate(),
      Number(clockOnly[1]),
      Number(clockOnly[2]),
      Number(clockOnly[3] ?? 0)
    ).getTime();
  }

  const parsed = Date.parse(timestamp);
  return Number.isNaN(parsed) ? 0 : parsed;
}

function sortLogItems(items: LogItem[], order: LogSortOrder) {
  return items
    .map((item, index) => ({ item, index, ts: logTimestampMs(item.timestamp) }))
    .sort((a, b) => {
      if (a.ts !== b.ts) return order === "desc" ? b.ts - a.ts : a.ts - b.ts;
      return a.index - b.index;
    })
    .map(({ item }) => item);
}

export default function ProbePage() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const tab = (params.get("tab") as Tab) || "errors";
  const { toast } = useApp();
  const inv = useInvestigation();
  const selectedServiceParam = params.get("svc") || "";

  function setTab(t: Tab) {
    setParams({ tab: t });
  }

  // ── Error feed (live polling) ──
  const [hoursBack, setHoursBack] = useState(1);
  const [errorLimit, setErrorLimit] = useState(200);
  const [errorSortOrder, setErrorSortOrder] = useState<LogSortOrder>("desc");
  const prevIds = useRef<Set<string>>(new Set());

  const errorFetcher = useCallback(
    () => probe.tailErrors(hoursBack, errorLimit, true),
    [hoursBack, errorLimit]
  );
  const { data: errorData, loading: errorLoading } = usePolling(
    errorFetcher, tab === "errors" ? 10000 : 0, [hoursBack, errorLimit]
  );

  // Track new items for animation
  const [newItemKeys, setNewItemKeys] = useState<Set<string>>(new Set());
  useEffect(() => {
    if (!errorData) return;
    const fresh = new Set<string>();
    errorData.items.forEach((item) => {
      const key = logItemFingerprint(item);
      if (!prevIds.current.has(key)) fresh.add(key);
    });
    if (fresh.size > 0 && prevIds.current.size > 0) {
      setNewItemKeys(fresh);
      setTimeout(() => setNewItemKeys(new Set()), 1200);
    }
    const nextSet = new Set<string>();
    errorData.items.forEach((item) => {
      nextSet.add(logItemFingerprint(item));
    });
    prevIds.current = nextSet;
  }, [errorData]);
  const errorItems = useMemo(
    () => sortLogItems(errorData?.items ?? [], errorSortOrder),
    [errorData, errorSortOrder]
  );

  // ── Search ──
  const [keyword, setKeyword] = useState("");
  const [level, setLevel] = useState("");
  const [searchLimit, setSearchLimit] = useState(200);
  const [searchSortOrder, setSearchSortOrder] = useState<LogSortOrder>("desc");
  const [searchResult, setSearchResult] = useState<SearchResult | null>(null);
  const [searchLoading, setSearchLoading] = useState(false);
  const searchItems = useMemo(
    () => sortLogItems(searchResult?.items ?? [], searchSortOrder),
    [searchResult, searchSortOrder]
  );

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

  // ── Service logs ──
  const [services, setServices] = useState<string[]>([]);
  const [serviceFilter, setServiceFilter] = useState("");
  const [selectedService, setSelectedService] = useState(selectedServiceParam);
  const [serviceHoursBack, setServiceHoursBack] = useState(1);
  const [serviceLimit, setServiceLimit] = useState(200);
  const [serviceSortOrder, setServiceSortOrder] = useState<LogSortOrder>("desc");
  const [serviceLevel, setServiceLevel] = useState("");
  const [serviceKeyword, setServiceKeyword] = useState("");
  const [serviceExcludeNoise, setServiceExcludeNoise] = useState(true);
  const [serviceResult, setServiceResult] = useState<SearchResult | null>(null);
  const [serviceLoading, setServiceLoading] = useState(false);
  const [serviceSource, setServiceSource] = useState("");
  const serviceItems = useMemo(
    () => sortLogItems(serviceResult?.items ?? [], serviceSortOrder),
    [serviceResult, serviceSortOrder]
  );

  async function loadServices() {
    try {
      const r = await probe.listServices();
      setServices(r.services);
      setServiceSource(r.source);
    } catch (e) {
      toast("error", e instanceof Error ? e.message : "服务列表加载失败");
    }
  }

  async function loadServiceLogs(
    service = selectedService,
    overrides: Partial<{
      hoursBack: number;
      level: string;
      keyword: string;
      limit: number;
      excludeNoise: boolean;
    }> = {}
  ) {
    const name = service.trim();
    if (!name) return;
    setSelectedService(name);
    setServiceLoading(true);
    try {
      const r = await probe.tailService(name, {
        hoursBack: overrides.hoursBack ?? serviceHoursBack,
        level: (overrides.level ?? serviceLevel) || undefined,
        keyword: (overrides.keyword ?? serviceKeyword).trim() || undefined,
        limit: overrides.limit ?? serviceLimit,
        includeFull: true,
        excludeNoise: overrides.excludeNoise ?? serviceExcludeNoise,
      });
      setServiceResult(r);
    } catch (e) {
      toast("error", e instanceof Error ? e.message : "服务日志加载失败");
    } finally {
      setServiceLoading(false);
    }
  }

  useEffect(() => {
    if (tab === "service") void loadServices();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab]);

  useEffect(() => {
    if (tab === "service" && selectedServiceParam) {
      setSelectedService(selectedServiceParam);
      void loadServiceLogs(selectedServiceParam);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, selectedServiceParam]);

  // ── Trace ──
  const traceRidParam = params.get("rid") || "";
  const traceHintParam = params.get("hint_time") || "";
  const traceBackParam = params.get("back_hours");
  const [requestId, setRequestId] = useState(traceRidParam);
  const [backHours, setBackHours] = useState(() =>
    traceBackHoursFromParams(traceBackParam, traceHintParam)
  );
  const [traceHintTime, setTraceHintTime] = useState(traceHintParam);
  const [traceResult, setTraceResult] = useState<TraceSummary | null>(null);
  const [traceLoading, setTraceLoading] = useState(false);
  const [diagnosisPack, setDiagnosisPack] = useState<DiagnosisPack | null>(null);
  const [diagnosisLoading, setDiagnosisLoading] = useState(false);

  // Auto-trace if rid is in URL
  useEffect(() => {
    if (traceRidParam && tab === "trace") {
      const nextBackHours = traceBackHoursFromParams(traceBackParam, traceHintParam);
      setRequestId(traceRidParam);
      setTraceHintTime(traceHintParam);
      setBackHours(nextBackHours);
      void doTrace(traceRidParam, {
        backHours: nextBackHours,
        hintTime: traceHintParam,
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, traceRidParam, traceHintParam, traceBackParam]);

  async function doTrace(
    rid?: string,
    options: { backHours?: number; hintTime?: string } = {}
  ) {
    const id = (rid || requestId).trim();
    if (!id) return;
    const nextBackHours = options.backHours ?? backHours;
    const nextHintTime = options.hintTime ?? traceHintTime;
    setTraceLoading(true);
    setDiagnosisPack(null);
    try {
      const r = await probe.trace(id, nextBackHours, nextHintTime || undefined);
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
    let copied = false;
    try {
      await navigator.clipboard.writeText(text);
      copied = true;
    } catch {
      copied = copyTextFallback(text);
    }

    if (copied) {
      toast("success", `已复制${label}`);
    } else {
      toast("error", "复制失败，浏览器没有开放剪贴板权限");
    }
  }

  function copyTextFallback(text: string) {
    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.setAttribute("readonly", "true");
    textarea.style.position = "fixed";
    textarea.style.left = "-9999px";
    textarea.style.top = "0";
    document.body.appendChild(textarea);
    textarea.focus();
    textarea.select();
    try {
      return document.execCommand("copy");
    } finally {
      document.body.removeChild(textarea);
    }
  }

  function formatLogItem(item: LogItem) {
    const parts = [
      item.timestamp,
      item.level,
      item.service ? `[${item.service}]` : "",
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

  function copyLogItems(items: LogItem[], label: string) {
    const lines = items.map(formatLogItem);
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
      const hintTime = normalizeTraceHintTime(item.timestamp);
      const nextBackHours = traceBackHoursFromTimestamp(item.timestamp);
      const query = new URLSearchParams({
        tab: "trace",
        rid: item.request_id,
        back_hours: String(nextBackHours),
      });
      if (hintTime) query.set("hint_time", hintTime);

      setRequestId(item.request_id);
      setTraceHintTime(hintTime);
      setBackHours(nextBackHours);
      inv.push({
        type: "trace",
        label: item.request_id.slice(0, 16),
        path: `/probe?${query.toString()}`,
        data: { request_id: item.request_id, hint_time: hintTime, back_hours: nextBackHours },
      });
    }
  }

  function analyzeTraceWithAgent(trace: TraceSummary) {
    const prompt = buildTraceAgentPrompt(trace);
    navigate(`/chat?prompt=${encodeURIComponent(prompt)}&auto_send=1`);
  }

  async function buildDiagnosisPack(trace: TraceSummary) {
    setDiagnosisLoading(true);
    try {
      const pack = await diagnosis.request({
        request_id: trace.request_id,
        back_hours: trace.searched_hours,
        hint_time: traceHintTime || undefined,
        include_lens_counts: true,
        max_entities: 3,
      });
      setDiagnosisPack(pack);
    } catch (e) {
      toast("error", e instanceof Error ? e.message : "证据包生成失败");
    } finally {
      setDiagnosisLoading(false);
    }
  }

  const filteredServices = services.filter((svc) =>
    svc.toLowerCase().includes(serviceFilter.trim().toLowerCase())
  );

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
            <button className={`tab-btn ${tab === "service" ? "active" : ""}`} onClick={() => setTab("service")}>
              服务日志
              {services.length > 0 && <span className="tab-count">{services.length}</span>}
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
              <select className="input" style={{ width: 140 }} value={errorSortOrder} onChange={(e) => setErrorSortOrder(e.target.value as LogSortOrder)}>
                <option value="desc">最新在前</option>
                <option value="asc">最早在前</option>
              </select>
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
                {errorItems.length > 0 ? (
                  errorItems.map((item, i) => (
                    <LogLineView
                      key={`${logItemFingerprint(item)}:${i}`}
                      item={item}
                      isNew={newItemKeys.has(logItemFingerprint(item))}
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
              <select className="input" style={{ width: 140 }} value={searchSortOrder} onChange={(e) => setSearchSortOrder(e.target.value as LogSortOrder)}>
                <option value="desc">最新在前</option>
                <option value="asc">最早在前</option>
              </select>
              <button className="btn btn-primary" onClick={handleSearch} disabled={searchLoading || !keyword.trim()}>
                {searchLoading ? <><span className="spinner" /> 搜索中</> : "搜索"}
              </button>
            </div>

            {searchResult && (
              <>
                <div className="row gap-sm mb-md">
                  <span className="badge badge-teal">命中 {searchResult.summary.total_matches} 条</span>
                  <button className="btn btn-ghost btn-sm" onClick={() => copyLogItems(searchItems, "搜索结果")} disabled={!searchItems.length}>
                    复制结果
                  </button>
                  {searchResult.summary.truncated && <span className="badge badge-warn">已到返回上限</span>}
                </div>

                <div className="card">
                  <div className="card-body flush" style={{ maxHeight: "calc(100vh - 300px)", overflowY: "auto" }}>
                    {searchItems.map((item, i) => (
                      <LogLineView
                        key={`${logItemFingerprint(item)}:${i}`}
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

        {/* ════ SERVICE LOGS TAB ════ */}
        {tab === "service" && (
          <div className="fade-up service-log-layout">
            <div className="card service-list-panel">
              <div className="card-head">
                <h3>服务列表</h3>
                <span className="badge badge-teal">{services.length}</span>
              </div>
              <div className="card-body">
                <div className="row gap-sm mb-sm">
                  <input
                    className="input"
                    placeholder="过滤服务名"
                    value={serviceFilter}
                    onChange={(e) => setServiceFilter(e.target.value)}
                  />
                  <button className="btn btn-ghost btn-sm" onClick={() => void loadServices()}>刷新</button>
                </div>
                {serviceSource && (
                  <div className="field-label mb-sm">来源：{serviceSourceLabel(serviceSource)}</div>
                )}
              </div>
              <div className="card-body flush service-list">
                {filteredServices.length > 0 ? (
                  filteredServices.map((svc) => (
                    <button
                      key={svc}
                      className={`service-list-item ${selectedService === svc ? "active" : ""}`}
                      type="button"
                      onClick={() => {
                        setParams({ tab: "service", svc });
                        void loadServiceLogs(svc);
                      }}
                    >
                      {svc}
                    </button>
                  ))
                ) : (
                  <div className="empty" style={{ padding: 18 }}>
                    <div className="empty-text">没有匹配的服务</div>
                  </div>
                )}
              </div>
            </div>

            <div className="service-log-panel">
              <div className="row gap-sm mb-md wrap">
                <input
                  className="input"
                  style={{ minWidth: 220, flex: 1 }}
                  placeholder="服务名，例如 jzadapter"
                  value={selectedService}
                  onChange={(e) => setSelectedService(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && loadServiceLogs()}
                />
                <select
                  className="input"
                  style={{ width: 140 }}
                  value={serviceHoursBack}
                  onChange={(e) => {
                    const next = Number(e.target.value);
                    setServiceHoursBack(next);
                    if (selectedService.trim()) void loadServiceLogs(selectedService, { hoursBack: next });
                  }}
                >
                  {[1, 2, 4, 8, 12, 24].map((h) => <option key={h} value={h}>最近 {h} 小时</option>)}
                </select>
                <select
                  className="input"
                  style={{ width: 120 }}
                  value={serviceLevel}
                  onChange={(e) => {
                    const next = e.target.value;
                    setServiceLevel(next);
                    if (selectedService.trim()) void loadServiceLogs(selectedService, { level: next });
                  }}
                >
                  <option value="">全部级别</option>
                  <option value="ERR">ERR</option>
                  <option value="WAR">WAR</option>
                  <option value="INF">INF</option>
                  <option value="DBG">DBG</option>
                </select>
                <select
                  className="input"
                  style={{ width: 130 }}
                  value={serviceLimit}
                  onChange={(e) => {
                    const next = Number(e.target.value);
                    setServiceLimit(next);
                    if (selectedService.trim()) void loadServiceLogs(selectedService, { limit: next });
                  }}
                >
                  {[50, 100, 200, 500].map((n) => <option key={n} value={n}>返回 {n} 条</option>)}
                </select>
                <select
                  className="input"
                  style={{ width: 140 }}
                  value={serviceSortOrder}
                  onChange={(e) => setServiceSortOrder(e.target.value as LogSortOrder)}
                >
                  <option value="desc">最新在前</option>
                  <option value="asc">最早在前</option>
                </select>
                <input
                  className="input"
                  style={{ minWidth: 180 }}
                  placeholder="可选关键词"
                  value={serviceKeyword}
                  onChange={(e) => setServiceKeyword(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && loadServiceLogs()}
                />
                <button className="btn btn-primary" onClick={() => loadServiceLogs()} disabled={serviceLoading || !selectedService.trim()}>
                  {serviceLoading ? <><span className="spinner" /> 加载中</> : "查看日志"}
                </button>
                <button className="btn btn-ghost btn-sm" onClick={() => copyLogItems(serviceItems, "服务日志")} disabled={!serviceItems.length}>
                  复制日志
                </button>
                <label className="check-control">
                  <input
                    type="checkbox"
                    checked={serviceExcludeNoise}
                    onChange={(e) => {
                      const next = e.target.checked;
                      setServiceExcludeNoise(next);
                      if (selectedService.trim()) void loadServiceLogs(selectedService, { excludeNoise: next });
                    }}
                  />
                  <span>隐藏注册/心跳</span>
                </label>
              </div>

              {serviceResult && (
                <>
                  <div className="row gap-sm mb-md">
                    <span className="badge badge-teal">显示 {serviceResult.summary.returned} 条</span>
                    {serviceResult.summary.time_range?.start && (
                      <span className="badge badge-teal">
                        {formatLogTime(serviceResult.summary.time_range.start)} - {formatLogTime(serviceResult.summary.time_range.end)}
                      </span>
                    )}
                    {serviceResult.summary.truncated && <span className="badge badge-warn">已到返回上限</span>}
                  </div>
                  <div className="card">
                    <div className="card-body flush" style={{ maxHeight: "calc(100vh - 330px)", overflowY: "auto" }}>
                      {serviceItems.length > 0 ? (
                        serviceItems.map((item, i) => (
                          <LogLineView
                            key={`${logItemFingerprint(item)}:${i}`}
                            item={item}
                            onOpenContext={openContext}
                            onTrace={traceLog}
                            onCopy={(target) => copyText(formatLogItem(target), "单条日志")}
                          />
                        ))
                      ) : (
                        <div className="empty" style={{ padding: 24 }}>
                          <div className="empty-text">这个服务在当前条件下没有日志</div>
                        </div>
                      )}
                    </div>
                  </div>
                </>
              )}
            </div>
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
                onChange={(e) => {
                  setRequestId(e.target.value);
                  setTraceHintTime("");
                }}
                onKeyDown={(e) => e.key === "Enter" && doTrace()}
                autoFocus
              />
              <select
                className="input"
                style={{ width: 160 }}
                value={backHours}
                onChange={(e) => {
                  setBackHours(Number(e.target.value));
                  setTraceHintTime("");
                }}
              >
                {traceBackOptions(backHours).map((h) => (
                  <option key={h} value={h}>
                    {traceBackOptionLabel(h, Boolean(traceHintTime))}
                  </option>
                ))}
              </select>
              <button className="btn btn-primary" onClick={() => doTrace()} disabled={traceLoading || !requestId.trim()}>
                {traceLoading ? <><span className="spinner" /> 查询中</> : "查询链路"}
              </button>
              {traceHintTime && (
                <span className="badge badge-amber">
                  {traceAutoHintLabel(traceHintTime, backHours)}
                </span>
              )}
            </div>

            {traceResult && (
              <TraceView
                trace={traceResult}
                diagnosisPack={diagnosisPack}
                diagnosisLoading={diagnosisLoading}
                onAnalyze={analyzeTraceWithAgent}
                onBuildDiagnosis={buildDiagnosisPack}
              />
            )}
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

function clipTraceMessage(message: string, max = 260): string {
  if (message.length <= max) return message;
  return `${message.slice(0, max)}...`;
}

function buildTraceAgentPrompt(trace: TraceSummary): string {
  const servicePath = trace.services.length > 0 ? trace.services.join(" -> ") : "未知";
  const errors = trace.errors.slice(0, 5)
    .map((item) => `- ${formatLogTime(item.timestamp)} [${item.service}] ${clipTraceMessage(item.message)}`)
    .join("\n") || "- 无错误日志摘要";
  const warns = trace.warns.slice(0, 3)
    .map((item) => `- ${formatLogTime(item.timestamp)} [${item.service}] ${clipTraceMessage(item.message)}`)
    .join("\n") || "- 无警告日志摘要";
  const suspects = (trace.suspects ?? []).slice(0, 5)
    .map((item) => `- ${formatLogTime(item.timestamp)} [${item.level}] [${item.service}] ${clipTraceMessage(item.message)}；原因：${item.reason}`)
    .join("\n") || "- 暂无候选异常点";

  return [
    "请对这个请求链路做一次排障分析。",
    "",
    `request_id: ${trace.request_id}`,
    `回看窗口: ${trace.searched_hours} 小时`,
    `服务路径: ${servicePath}`,
    `错误数: ${trace.error_count}`,
    `警告数: ${trace.warn_count}`,
    "",
    "错误摘要:",
    errors,
    "",
    "警告摘要:",
    warns,
    "",
    "候选异常点:",
    suspects,
    "",
    "要求:",
    "1. 先调用 meridian_diagnose_request，include_lens_counts=true，自动收集 Probe/Atlas/Lens 证据。",
    "2. 如果证据包不足，再用 probe_search_by_request_id(include_full=true) 或 Atlas/Lens 低层工具补证据。",
    "3. 输出关键证据列表，按服务和时间排序。",
    "4. 给出最可能的候选原因，但不要下最终结论。",
    "5. 给出下一步应该查哪个服务、关键词或业务数据。",
  ].join("\n");
}

function DiagnosisPackView({ pack }: { pack: DiagnosisPack }) {
  const atlasQueries = pack.atlas_queries ?? [];
  const lensCandidates = pack.lens_candidates ?? [];
  const suspectCount = pack.trace?.suspects?.length ?? 0;

  return (
    <div className="card mb-md" style={{ borderLeftColor: "var(--teal)", borderLeftWidth: 3 }}>
      <div className="card-head">
        <h3>诊断证据包</h3>
        <div className="row gap-sm wrap">
          <span className="badge badge-teal">{atlasQueries.length} 个 Atlas 查询</span>
          <span className="badge badge-emerald">{lensCandidates.length} 个 Lens 候选</span>
          <span className="badge badge-coral">{suspectCount} 个异常点</span>
        </div>
      </div>
      <div className="card-body" style={{ display: "grid", gap: 12 }}>
        {atlasQueries.length > 0 && (
          <div>
            <div className="field-label mb-sm">Atlas 命中</div>
            <div className="row gap-xs wrap">
              {atlasQueries.map((query, index) => (
                <span key={`${query.query}-${index}`} className="badge badge-dim">
                  {query.query}: {query.matched_service?.length ?? 0} 服务 / {query.matched_table?.length ?? 0} 表 / {query.matched_column?.length ?? 0} 字段
                </span>
              ))}
            </div>
          </div>
        )}
        {lensCandidates.length > 0 ? (
          <div>
            <div className="field-label mb-sm">Lens 候选实体</div>
            <div style={{ display: "grid", gap: 8 }}>
              {lensCandidates.map((candidate, index) => (
                <div key={`${candidate.summary?.name ?? index}`} className="row gap-xs wrap">
                  <span className="badge badge-teal">{candidate.summary?.display_name || candidate.summary?.name}</span>
                  <span className="badge badge-dim">score {candidate.score}</span>
                  {candidate.count && (
                    <span className="badge badge-emerald">
                      count {Number(candidate.count.count ?? 0).toLocaleString()}
                    </span>
                  )}
                  {candidate.detail?.primary_table && (
                    <span className="badge badge-dim">{candidate.detail.database}.{candidate.detail.primary_table}</span>
                  )}
                </div>
              ))}
            </div>
          </div>
        ) : (
          <div className="empty" style={{ padding: 10 }}>
            <div className="empty-text">没有匹配到 Lens 业务实体；可以让 Agent 根据异常服务或关键词继续查 Atlas。</div>
          </div>
        )}
      </div>
    </div>
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
      {item.service && <span className="log-service">[{item.service}]</span>}
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
  diagnosisPack,
  diagnosisLoading,
  onAnalyze,
  onBuildDiagnosis,
}: {
  trace: TraceSummary;
  diagnosisPack: DiagnosisPack | null;
  diagnosisLoading: boolean;
  onAnalyze: (trace: TraceSummary) => void;
  onBuildDiagnosis: (trace: TraceSummary) => void;
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

      {/* Request path */}
      <div className="card mb-md">
        <div className="card-head">
          <h3>请求路径</h3>
          <div className="row gap-sm wrap">
            <button className="btn btn-primary btn-sm" type="button" onClick={() => onAnalyze(trace)}>
              交给 Agent 分析
            </button>
            <button className="btn btn-ghost btn-sm" type="button" onClick={() => onBuildDiagnosis(trace)} disabled={diagnosisLoading}>
              {diagnosisLoading ? <><span className="spinner" /> 生成中</> : "生成证据包"}
            </button>
            <span className="badge badge-dim">
              {trace.searched_hours > 0 ? `已回看 ${trace.searched_hours} 小时` : "当前小时"}
            </span>
            <span style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--t4)" }}>
              {trace.time_range}
            </span>
          </div>
        </div>
        <div className="card-body">
          <div className="row gap-sm wrap">
            {trace.services.map((svc, i) => (
              <span key={svc} className="row gap-sm">
                <span className="badge badge-teal">{svc}</span>
                {i < trace.services.length - 1 && (
                  <span style={{ color: "var(--t4)", fontSize: 11 }}>{"\u2192"}</span>
                )}
              </span>
            ))}
          </div>
        </div>
      </div>

      {diagnosisPack && <DiagnosisPackView pack={diagnosisPack} />}

      {Object.keys(trace.service_stats ?? {}).length > 0 && (
        <div className="card mb-md">
          <div className="card-head">
            <h3>服务统计</h3>
          </div>
          <div className="card-body flush" style={{ overflowX: "auto" }}>
            <table className="dtable">
              <thead>
                <tr>
                  <th>服务</th>
                  <th>日志</th>
                  <th>错误</th>
                  <th>警告</th>
                  <th>首次出现</th>
                  <th>最后出现</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(trace.service_stats ?? {}).map(([service, stat]) => (
                  <tr key={service}>
                    <td className="mono">{service}</td>
                    <td>{stat.total}</td>
                    <td><span className={stat.error > 0 ? "badge badge-coral" : "badge badge-dim"}>{stat.error}</span></td>
                    <td><span className={stat.warn > 0 ? "badge badge-warn" : "badge badge-dim"}>{stat.warn}</span></td>
                    <td className="mono">{formatLogTime(stat.first_seen)}</td>
                    <td className="mono">{formatLogTime(stat.last_seen)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Hint */}
      {trace.hint && (
        <div className="card mb-md" style={{ borderLeftColor: "var(--warn)", borderLeftWidth: 3 }}>
          <div className="card-body" style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--warn)", lineHeight: 1.6 }}>
            {trace.hint}
          </div>
        </div>
      )}

      {/* Suspects */}
      {(trace.suspects ?? []).length > 0 && (
        <div className="card mb-md" style={{ borderLeftColor: "var(--coral)", borderLeftWidth: 3 }}>
          <div className="card-head">
            <h3 style={{ color: "var(--coral)" }}>候选异常点</h3>
            <span className="badge badge-coral">{trace.suspects?.length ?? 0}</span>
          </div>
          <div className="card-body flush" style={{ maxHeight: 260, overflowY: "auto" }}>
            {(trace.suspects ?? []).map((item, i) => (
              <div key={`${item.service}-${item.timestamp}-${i}`} className="log-line">
                <span className="log-ts">{formatLogTime(item.timestamp)}</span>
                <span className={`log-level ${item.level}`}>{item.level}</span>
                <span className="log-svc">[{item.service}]</span>
                <span className="log-msg">
                  {item.message}
                  <span style={{ color: "var(--t4)", marginLeft: 8 }}>{item.reason}</span>
                </span>
              </div>
            ))}
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
                <span className="log-svc">[{e.service}]</span>
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
                <span className="log-svc">[{t.service}]</span>
                <span className="log-msg">{t.message}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
