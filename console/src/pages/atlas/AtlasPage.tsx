import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useApp } from "../../context/AppContext";
import { useInvestigation } from "../../context/InvestigationContext";
import {
  atlas,
  type AtlasStatus,
  type ServiceInfo,
  type TableSummary,
  type TableInfo,
  type Annotation,
} from "../../api/client";
import { serviceDatabases, serviceSourceLabel, serviceStatusBadge, serviceStatusLabel } from "../../utils/serviceLabels";

type Tab = "schemas" | "services" | "annotations";

export default function AtlasPage() {
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") as Tab) || "schemas";
  const targetService = params.get("svc") || "";
  const { toast } = useApp();
  const inv = useInvestigation();

  const [status, setStatus] = useState<AtlasStatus | null>(null);
  const [services, setServices] = useState<ServiceInfo[]>([]);
  const [refreshing, setRefreshing] = useState(false);

  // Schema browsing state
  const [databases, setDatabases] = useState<Array<{ database: string; table_count: number; snapshot_count: number; last_collected: string }>>([]);
  const [selectedDb, setSelectedDb] = useState(params.get("db") || "");
  const [tables, setTables] = useState<TableSummary[]>([]);
  const [selectedTable, setSelectedTable] = useState<TableInfo | null>(null);
  const [tableLoading, setTableLoading] = useState(false);
  const [tableQuery, setTableQuery] = useState("");
  const [serviceQuery, setServiceQuery] = useState("");

  // Annotation state
  const [annotations, setAnnotations] = useState<Annotation[]>([]);
  const [annotationTotal, setAnnotationTotal] = useState(0);
  const [annotationPage, setAnnotationPage] = useState(1);
  const [annotationPageSize, setAnnotationPageSize] = useState(100);
  const [annotationQuery, setAnnotationQuery] = useState("");
  const [annotationTableFilter, setAnnotationTableFilter] = useState("");
  const [annotationSource, setAnnotationSource] = useState("");
  const [annotationStatus, setAnnotationStatus] = useState("");
  const [annotationLoading, setAnnotationLoading] = useState(false);
  const [selectedAnnotationKeys, setSelectedAnnotationKeys] = useState<string[]>([]);
  const [annotateDb, setAnnotateDb] = useState("");
  const [annotateTable, setAnnotateTable] = useState("");
  const [annotateCol, setAnnotateCol] = useState("");
  const [annotateSemantic, setAnnotateSemantic] = useState("");
  const [annotating, setAnnotating] = useState(false);

  // Search
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResult, setSearchResult] = useState<{
    matched_table: TableInfo[];
    matched_column: Array<Record<string, string>>;
  } | null>(null);

  // Collecting
  const [collecting, setCollecting] = useState(false);

  useEffect(() => {
    loadStatus();
    loadDatabases();
    atlas.listServices().then((r) => setServices(r.service)).catch(() => {});
  }, []);

  useEffect(() => {
    const db = params.get("db") || "";
    if (db && db !== selectedDb) setSelectedDb(db);
  }, [params, selectedDb]);

  // When db is selected, load its tables
  useEffect(() => {
    if (selectedDb) {
      loadTables(selectedDb);
      setAnnotationPage(1);
      setSelectedAnnotationKeys([]);
    }
  }, [selectedDb]);

  useEffect(() => {
    if (selectedDb) void loadAnnotations(selectedDb);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedDb, annotationPage, annotationPageSize, annotationTableFilter, annotationSource, annotationStatus]);

  async function loadStatus() {
    try {
      setStatus(await atlas.status());
    } catch { /* offline */ }
  }

  async function loadDatabases() {
    try {
      const r = await atlas.listDatabases();
      setDatabases(r.databases);
      // Auto-select first or URL param
      if (r.databases.length > 0 && !selectedDb) {
        setSelectedDb(r.databases[0].database);
      }
    } catch { /* offline */ }
  }

  async function loadTables(db: string) {
    try {
      const r = await atlas.listTables(db);
      setTables(r.tables);
      setSelectedTable(null);
    } catch {
      setTables([]);
    }
  }

  async function loadAnnotations(db: string) {
    setAnnotationLoading(true);
    try {
      const confirmed =
        annotationStatus === "confirmed"
          ? true
          : annotationStatus === "pending"
            ? false
            : undefined;
      const r = await atlas.listAnnotations(db, {
        table: annotationTableFilter || undefined,
        q: annotationQuery.trim() || undefined,
        source: annotationSource || undefined,
        confirmed,
        limit: annotationPageSize,
        offset: (annotationPage - 1) * annotationPageSize,
      });
      setAnnotations(r.annotations);
      setAnnotationTotal(r.total ?? r.count);
      setSelectedAnnotationKeys([]);
    } catch {
      setAnnotations([]);
      setAnnotationTotal(0);
    }
    setAnnotationLoading(false);
  }

  async function selectTable(db: string, tableName: string) {
    setTableLoading(true);
    try {
      const detail = await atlas.getTable(db, tableName);
      setSelectedTable(detail);
    } catch {
      toast("error", `表结构加载失败：${tableName}`);
    }
    setTableLoading(false);
  }

  async function handleCollect() {
    setCollecting(true);
    try {
      const r = await atlas.collectSchema(selectedDb || undefined);
      toast("success", `已采集 ${r.collected} 个数据库`);
      await loadDatabases();
      if (selectedDb) await loadTables(selectedDb);
    } catch (e) {
      toast("error", e instanceof Error ? e.message : "采集失败");
    }
    setCollecting(false);
  }

  async function handleAnnotate() {
    if (!annotateDb || !annotateTable || !annotateCol || !annotateSemantic) return;
    setAnnotating(true);
    try {
      await atlas.annotate({
        database: annotateDb,
        table: annotateTable,
        column: annotateCol,
        semantic: annotateSemantic,
        source: "manual",
      });
      toast("success", `已标注 ${annotateCol}`);
      setAnnotateSemantic("");
      if (annotateDb === selectedDb) await loadAnnotations(selectedDb);
    } catch (e) {
      toast("error", e instanceof Error ? e.message : "标注失败");
    }
    setAnnotating(false);
  }

  async function handleConfirm(ann: Annotation, confirmed: boolean) {
    try {
      await atlas.confirmAnnotation({
        database: annotationDatabase(ann),
        table: annotationTable(ann),
        column: annotationColumn(ann),
        confirmed,
      });
      toast("success", confirmed ? "已确认" : "已驳回");
      await loadAnnotations(annotationDatabase(ann));
    } catch {
      toast("error", "操作失败");
    }
  }

  async function handleBatchConfirm(confirmed: boolean) {
    const selected = annotations.filter((ann) => selectedAnnotationKeys.includes(annotationKey(ann)));
    if (!selected.length) return;
    try {
      const r = await atlas.confirmAnnotations({
        annotations: selected.map((ann) => ({
          database: annotationDatabase(ann),
          table: annotationTable(ann),
          column: annotationColumn(ann),
        })),
        confirmed,
      });
      toast("success", confirmed ? `已确认 ${r.success} 条` : `已驳回 ${r.success} 条`);
      await loadAnnotations(selectedDb);
    } catch {
      toast("error", "批量操作失败");
    }
  }

  async function handleSearch() {
    if (!searchQuery.trim()) return;
    try {
      const r = await atlas.searchMeta(searchQuery.trim());
      setSearchResult({ matched_table: r.matched_table, matched_column: r.matched_column });
    } catch {
      toast("error", "搜索失败");
    }
  }

  async function handleRefreshServices() {
    setRefreshing(true);
    try {
      const r = await atlas.refreshServices();
      setServices(r.service);
      toast("success", `发现 ${r.count} 个服务`);
    } catch {
      toast("error", "刷新失败");
    }
    setRefreshing(false);
  }

  function setTab(t: Tab) {
    setParams({ tab: t, ...(selectedDb ? { db: selectedDb } : {}) });
  }

  const filteredTables = useMemo(() => {
    const query = tableQuery.trim().toLowerCase();
    if (!query) return tables;
    return tables.filter((t) =>
      [t.name, t.comment, t.engine]
        .filter(Boolean)
        .some((value) => value.toLowerCase().includes(query))
    );
  }, [tables, tableQuery]);

  const filteredServices = useMemo(() => {
    const query = serviceQuery.trim().toLowerCase();
    if (!query) return services;
    return services.filter((svc) =>
      [
        svc.name,
        svc.status,
        svc.source ?? "",
        svc.deploy_path,
        svc.log_path,
        ...serviceDatabases(svc),
      ]
        .filter(Boolean)
        .some((value) => value.toLowerCase().includes(query))
    );
  }, [services, serviceQuery]);

  const annotationPageCount = Math.max(1, Math.ceil(annotationTotal / annotationPageSize));
  const currentAnnotationKeys = annotations.map(annotationKey);
  const allCurrentAnnotationsSelected =
    currentAnnotationKeys.length > 0 &&
    currentAnnotationKeys.every((key) => selectedAnnotationKeys.includes(key));

  function annotationDatabase(ann: Annotation) {
    return ann.database || ann.database_name || selectedDb;
  }

  function annotationTable(ann: Annotation) {
    return ann.table || ann.table_name || "";
  }

  function annotationColumn(ann: Annotation) {
    return ann.column || ann.column_name || "";
  }

  function annotationKey(ann: Annotation) {
    return `${annotationDatabase(ann)}.${annotationTable(ann)}.${annotationColumn(ann)}`;
  }

  function toggleAnnotationSelection(key: string) {
    setSelectedAnnotationKeys((prev) =>
      prev.includes(key) ? prev.filter((item) => item !== key) : [...prev, key]
    );
  }

  function toggleCurrentPageAnnotations() {
    if (allCurrentAnnotationsSelected) {
      setSelectedAnnotationKeys((prev) => prev.filter((key) => !currentAnnotationKeys.includes(key)));
    } else {
      setSelectedAnnotationKeys((prev) => Array.from(new Set([...prev, ...currentAnnotationKeys])));
    }
  }

  function applyAnnotationFilters() {
    if (annotationPage === 1) {
      void loadAnnotations(selectedDb);
    } else {
      setAnnotationPage(1);
    }
  }

  return (
    <>
      <div className="page-header">
        <div className="flex-between">
          <div>
            <h2>Atlas</h2>
            <div className="page-desc">元数据中心 — Schema 浏览、语义标注、服务发现</div>
          </div>
          <div className="row gap-sm">
            <button className="btn btn-ghost btn-sm" onClick={handleCollect} disabled={collecting}>
              {collecting ? <><span className="spinner" /> 采集中</> : "采集 Schema"}
            </button>
          </div>
        </div>
        <div className="page-toolbar">
          <div className="tab-bar">
            <button className={`tab-btn ${tab === "schemas" ? "active" : ""}`} onClick={() => setTab("schemas")}>
              Schema 浏览
            </button>
            <button className={`tab-btn ${tab === "annotations" ? "active" : ""}`} onClick={() => setTab("annotations")}>
              语义标注
              {annotations.filter((a) => !a.confirmed).length > 0 && (
                <span className="tab-count">{annotations.filter((a) => !a.confirmed).length}</span>
              )}
            </button>
            <button className={`tab-btn ${tab === "services" ? "active" : ""}`} onClick={() => setTab("services")}>
              服务发现 ({services.length})
            </button>
          </div>
        </div>
      </div>

      <div className="page-body" style={tab === "schemas" ? { display: "flex", gap: 14, overflow: "hidden", padding: "14px 28px 28px" } : undefined}>

        {/* ════ SCHEMA BROWSER ════ */}
        {tab === "schemas" && (
          <>
            {/* Left panel: DB + table list */}
            <div style={{ width: 280, flexShrink: 0, display: "flex", flexDirection: "column", gap: 10 }}>
              {/* Database selector */}
              <div className="card fade-up">
                <div className="card-head">
                  <h3>数据库</h3>
                  <span className="badge badge-teal">{databases.length}</span>
                </div>
                <div className="card-body flush">
                  {databases.length > 0 ? databases.map((db) => (
                    <div
                      key={db.database}
                      onClick={() => setSelectedDb(db.database)}
                      style={{
                        padding: "10px 14px",
                        borderBottom: "1px solid var(--border-0)",
                        cursor: "pointer",
                        background: selectedDb === db.database ? "var(--amber-glow)" : "transparent",
                        transition: "background 0.15s",
                      }}
                      onMouseEnter={(e) => { if (selectedDb !== db.database) e.currentTarget.style.background = "rgba(255,255,255,0.02)"; }}
                      onMouseLeave={(e) => { if (selectedDb !== db.database) e.currentTarget.style.background = "transparent"; }}
                    >
                      <div style={{ fontFamily: "var(--font-mono)", fontSize: 13, fontWeight: 500 }}>{db.database}</div>
                      <div className="row gap-xs mt-xs">
                        <span className="badge badge-dim">{db.table_count} 张表</span>
                        <span className="badge badge-dim">{db.snapshot_count} 快照</span>
                      </div>
                    </div>
                  )) : (
                    <div className="empty" style={{ padding: 20 }}>
                      <div className="empty-text">还没有数据库快照，请先点击上方“采集 Schema”。</div>
                    </div>
                  )}
                </div>
              </div>

              {/* Table list */}
              {selectedDb && (
                <div className="card fade-up stagger-1" style={{ flex: 1, display: "flex", flexDirection: "column" }}>
                  <div className="card-head">
                    <h3>{selectedDb} 的表</h3>
                    <span className="badge badge-teal">
                      {filteredTables.length}/{tables.length}
                    </span>
                  </div>
                  <div className="card-body" style={{ borderBottom: "1px solid var(--border-0)" }}>
                    <input
                      className="input"
                      placeholder="过滤表名、注释或引擎"
                      value={tableQuery}
                      onChange={(e) => setTableQuery(e.target.value)}
                    />
                  </div>
                  <div className="card-body flush" style={{ flex: 1, overflowY: "auto" }}>
                    {filteredTables.length > 0 ? filteredTables.map((t) => (
                      <div
                        key={t.name}
                        onClick={() => selectTable(selectedDb, t.name)}
                        style={{
                          padding: "8px 14px",
                          borderBottom: "1px solid var(--border-0)",
                          cursor: "pointer",
                          background: selectedTable?.name === t.name ? "var(--amber-glow)" : "transparent",
                          transition: "background 0.15s",
                        }}
                        onMouseEnter={(e) => { if (selectedTable?.name !== t.name) e.currentTarget.style.background = "rgba(255,255,255,0.02)"; }}
                        onMouseLeave={(e) => { if (selectedTable?.name !== t.name) e.currentTarget.style.background = "transparent"; }}
                      >
                        <div style={{ fontFamily: "var(--font-mono)", fontSize: 12 }}>{t.name}</div>
                        <div className="row gap-xs mt-xs">
                          <span style={{ fontSize: 11, color: "var(--t4)" }}>{t.column_count} 列</span>
                          {t.row_count_approx > 0 && (
                            <span style={{ fontSize: 11, color: "var(--t4)" }}>约 {t.row_count_approx.toLocaleString()} 行</span>
                          )}
                        </div>
                        {t.comment && (
                          <div style={{ fontSize: 11, color: "var(--t3)", marginTop: 2 }}>{t.comment}</div>
                        )}
                      </div>
                    )) : (
                      <div className="empty" style={{ padding: 20 }}>
                        <div className="empty-text">没有匹配的表</div>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>

            {/* Right panel: table detail + search */}
            <div style={{ flex: 1, overflowY: "auto", minWidth: 0 }}>
              {/* Search bar */}
              <div className="row gap-sm mb-md fade-up">
                <input
                  className="input"
                  style={{ flex: 1 }}
                  placeholder="搜索表、字段、注释或语义"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && handleSearch()}
                />
                <button className="btn btn-primary btn-sm" onClick={handleSearch} disabled={!searchQuery.trim()}>
                  搜索
                </button>
              </div>

              {/* Search results */}
              {searchResult && (
                <div className="card mb-md fade-up">
                  <div className="card-head">
                    <h3>搜索结果</h3>
                    <button className="btn btn-ghost btn-sm" onClick={() => setSearchResult(null)}>清除</button>
                  </div>
                  <div className="card-body">
                    {searchResult.matched_table.length > 0 && (
                      <div className="mb-md">
                        <div className="field-label mb-sm">匹配的表 ({searchResult.matched_table.length})</div>
                        <div className="row gap-sm wrap">
                          {searchResult.matched_table.map((t) => (
                            <span
                              key={`${t.database}.${t.name}`}
                              className="badge badge-teal"
                              style={{ cursor: "pointer" }}
                              onClick={() => { setSelectedDb(t.database); selectTable(t.database, t.name); }}
                            >
                              {t.database}.{t.name}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}
                    {searchResult.matched_column.length > 0 && (
                      <div>
                        <div className="field-label mb-sm">匹配的字段 ({searchResult.matched_column.length})</div>
                        {searchResult.matched_column.map((c, i) => (
                          <div key={i} className="row gap-sm mb-sm" style={{ fontSize: 12 }}>
                            <span className="mono" style={{ color: "var(--teal)", cursor: "pointer" }}
                              onClick={() => { setSelectedDb(c.database); selectTable(c.database, c.table); }}
                            >
                              {c.database}.{c.table}.{c.column}
                            </span>
                            {c.semantic && <span className="badge badge-amber">{c.semantic}</span>}
                          </div>
                        ))}
                      </div>
                    )}
                    {searchResult.matched_table.length === 0 && searchResult.matched_column.length === 0 && (
                      <div className="empty" style={{ padding: 16 }}>
                        <div className="empty-text">没有找到匹配项</div>
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* Table detail */}
              {selectedTable ? (
                <div className="card fade-up">
                  <div className="card-head">
                    <div className="row gap-sm">
                      <h3 style={{ textTransform: "none", letterSpacing: 0, fontSize: 14 }}>
                        {selectedTable.database}.{selectedTable.name}
                      </h3>
                      {selectedTable.engine && <span className="badge badge-dim">{selectedTable.engine}</span>}
                      {selectedTable.row_count_approx > 0 && (
                        <span className="badge badge-dim">约 {selectedTable.row_count_approx.toLocaleString()} 行</span>
                      )}
                    </div>
                    <button
                      className="btn btn-ghost btn-sm"
                      onClick={() =>
                        inv.push({
                          type: "entity",
                          label: `查询 ${selectedTable.name}`,
                          path: `/lens?entity=${encodeURIComponent(`${selectedTable.database}__${selectedTable.name}`)}&db=${encodeURIComponent(selectedTable.database)}&table=${encodeURIComponent(selectedTable.name)}&action=count`,
                          data: {
                            database: selectedTable.database,
                            table: selectedTable.name,
                            entity: `${selectedTable.database}__${selectedTable.name}`,
                          },
                        })
                      }
                    >
                      在 Lens 查询
                    </button>
                  </div>
                  {selectedTable.comment && (
                    <div style={{ padding: "8px 16px", fontSize: 12, color: "var(--t3)", borderBottom: "1px solid var(--border-0)" }}>
                      {selectedTable.comment}
                    </div>
                  )}
                  <div className="card-body flush" style={{ overflowX: "auto" }}>
                    <table className="dtable">
                      <thead>
                        <tr>
                          <th>字段</th>
                          <th>类型</th>
                          <th>可空</th>
                          <th>键</th>
                          <th>注释</th>
                          <th>语义</th>
                          <th>操作</th>
                        </tr>
                      </thead>
                      <tbody>
                        {selectedTable.column.map((col) => (
                          <tr key={col.name}>
                            <td className="mono" style={{ fontWeight: col.is_primary_key ? 600 : 400 }}>
                              {col.is_primary_key && <span style={{ color: "var(--amber)", marginRight: 4 }} title="Primary Key">PK</span>}
                              {col.name}
                            </td>
                            <td><span className="badge badge-dim">{col.type}</span></td>
                            <td style={{ color: col.nullable ? "var(--t4)" : "var(--coral)" }}>
                              {col.nullable ? "YES" : "NOT NULL"}
                            </td>
                            <td>
                              {col.is_primary_key && <span className="badge badge-amber">PK</span>}
                              {col.is_index && !col.is_primary_key && <span className="badge badge-dim">IDX</span>}
                            </td>
                            <td style={{ fontSize: 12, color: "var(--t3)", maxWidth: 200 }}>{col.comment || "\u2014"}</td>
                            <td>
                              {col.semantic ? (
                                <span className="badge badge-teal">{col.semantic}</span>
                              ) : (
                                <span style={{ color: "var(--t4)", fontSize: 11 }}>未标注</span>
                              )}
                            </td>
                            <td>
                              <button
                                className="btn btn-ghost btn-sm"
                                style={{ fontSize: 10, padding: "2px 6px" }}
                                onClick={() => {
                                  setAnnotateDb(selectedTable.database);
                                  setAnnotateTable(selectedTable.name);
                                  setAnnotateCol(col.name);
                                  setTab("annotations" as Tab);
                                }}
                              >
                                标注
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              ) : tableLoading ? (
                <div className="card">
                  <div className="card-body"><div className="empty"><div className="empty-text">加载中...</div></div></div>
                </div>
              ) : (
                <div className="card fade-up">
                  <div className="card-body">
                    <div className="empty" style={{ height: 300 }}>
                      <div className="empty-icon">{"\u2637"}</div>
                      <div className="empty-text">从左侧选择一张表查看结构</div>
                    </div>
                  </div>
                </div>
              )}
            </div>
          </>
        )}

        {/* ════ ANNOTATIONS TAB ════ */}
        {tab === "annotations" && (
          <div className="fade-up">
            {/* Add annotation form */}
            <div className="card mb-md">
              <div className="card-head"><h3>新增语义标注</h3></div>
              <div className="card-body">
                <div className="row gap-sm mb-sm">
                  <div style={{ flex: 1 }}>
                    <div className="field-label mb-sm">数据库</div>
                    <select className="input" value={annotateDb} onChange={(e) => setAnnotateDb(e.target.value)}>
                      <option value="">请选择...</option>
                      {databases.map((d) => <option key={d.database} value={d.database}>{d.database}</option>)}
                    </select>
                  </div>
                  <div style={{ flex: 1 }}>
                    <div className="field-label mb-sm">表</div>
                    <input className="input" value={annotateTable} onChange={(e) => setAnnotateTable(e.target.value)} placeholder="table_name" />
                  </div>
                  <div style={{ flex: 1 }}>
                    <div className="field-label mb-sm">字段</div>
                    <input className="input" value={annotateCol} onChange={(e) => setAnnotateCol(e.target.value)} placeholder="column_name" />
                  </div>
                </div>
                <div className="row gap-sm">
                  <div style={{ flex: 1 }}>
                    <div className="field-label mb-sm">语义说明</div>
                    <input
                      className="input"
                      value={annotateSemantic}
                      onChange={(e) => setAnnotateSemantic(e.target.value)}
                      placeholder="例如：用户手机号、订单创建时间"
                      onKeyDown={(e) => e.key === "Enter" && handleAnnotate()}
                    />
                  </div>
                  <div style={{ paddingTop: 22 }}>
                    <button className="btn btn-primary" onClick={handleAnnotate} disabled={annotating || !annotateDb || !annotateTable || !annotateCol || !annotateSemantic}>
                      {annotating ? <><span className="spinner" /> 保存中</> : "保存"}
                    </button>
                  </div>
                </div>
              </div>
            </div>

            {/* Existing annotations */}
            <div className="card">
              <div className="card-head">
                <h3>
                  语义标注
                  {selectedDb && <span style={{ color: "var(--teal)", marginLeft: 6, textTransform: "none" }}>({selectedDb})</span>}
                </h3>
                <div className="row gap-sm">
                  <select className="input" style={{ width: 160 }} value={selectedDb} onChange={(e) => setSelectedDb(e.target.value)}>
                    <option value="">选择数据库...</option>
                    {databases.map((d) => <option key={d.database} value={d.database}>{d.database}</option>)}
                  </select>
                  <span className="badge badge-teal">{annotationTotal}</span>
                </div>
              </div>
              <div className="card-body" style={{ borderBottom: "1px solid var(--border-0)" }}>
                <div className="row gap-sm wrap">
                  <input
                    className="input"
                    style={{ minWidth: 220, flex: 1 }}
                    placeholder="搜索表、字段或语义"
                    value={annotationQuery}
                    onChange={(e) => setAnnotationQuery(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && applyAnnotationFilters()}
                  />
                  <select
                    className="input"
                    style={{ width: 220 }}
                    value={annotationTableFilter}
                    onChange={(e) => {
                      setAnnotationTableFilter(e.target.value);
                      setAnnotationPage(1);
                    }}
                  >
                    <option value="">全部表</option>
                    {tables.map((t) => <option key={t.name} value={t.name}>{t.name}</option>)}
                  </select>
                  <select
                    className="input"
                    style={{ width: 120 }}
                    value={annotationSource}
                    onChange={(e) => {
                      setAnnotationSource(e.target.value);
                      setAnnotationPage(1);
                    }}
                  >
                    <option value="">全部来源</option>
                    <option value="manual">manual</option>
                    <option value="ai">ai</option>
                    <option value="rule">rule</option>
                    <option value="auto">auto</option>
                  </select>
                  <select
                    className="input"
                    style={{ width: 120 }}
                    value={annotationStatus}
                    onChange={(e) => {
                      setAnnotationStatus(e.target.value);
                      setAnnotationPage(1);
                    }}
                  >
                    <option value="">全部状态</option>
                    <option value="pending">待确认</option>
                    <option value="confirmed">已确认</option>
                  </select>
                  <button className="btn btn-primary btn-sm" onClick={applyAnnotationFilters} disabled={!selectedDb}>
                    搜索
                  </button>
                </div>
                <div className="row gap-sm mt-sm wrap">
                  <button
                    className="btn btn-ghost btn-sm"
                    onClick={() => handleBatchConfirm(true)}
                    disabled={selectedAnnotationKeys.length === 0}
                  >
                    批量确认 {selectedAnnotationKeys.length || ""}
                  </button>
                  <button
                    className="btn btn-danger btn-sm"
                    onClick={() => handleBatchConfirm(false)}
                    disabled={selectedAnnotationKeys.length === 0}
                  >
                    批量驳回 {selectedAnnotationKeys.length || ""}
                  </button>
                  <select
                    className="input"
                    style={{ width: 110 }}
                    value={annotationPageSize}
                    onChange={(e) => {
                      setAnnotationPageSize(Number(e.target.value));
                      setAnnotationPage(1);
                    }}
                  >
                    {[50, 100, 200, 500].map((n) => <option key={n} value={n}>{n} 条/页</option>)}
                  </select>
                  {annotationLoading && <span className="badge badge-amber"><span className="spinner" /> 加载中</span>}
                </div>
              </div>
              <div className="card-body flush" style={{ maxHeight: 520, overflowY: "auto" }}>
                {annotations.length > 0 ? (
                  <table className="dtable">
                    <thead>
                      <tr>
                        <th style={{ width: 34 }}>
                          <input
                            type="checkbox"
                            checked={allCurrentAnnotationsSelected}
                            onChange={toggleCurrentPageAnnotations}
                          />
                        </th>
                        <th>表.字段</th>
                        <th>语义</th>
                        <th>来源</th>
                        <th>状态</th>
                        <th>操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      {annotations.map((ann) => {
                        const key = annotationKey(ann);
                        return (
                        <tr key={key}>
                          <td>
                            <input
                              type="checkbox"
                              checked={selectedAnnotationKeys.includes(key)}
                              onChange={() => toggleAnnotationSelection(key)}
                            />
                          </td>
                          <td className="mono">{annotationTable(ann)}.{annotationColumn(ann)}</td>
                          <td style={{ color: "var(--teal)" }}>{ann.semantic}</td>
                          <td><span className={`badge ${ann.source === "manual" ? "badge-amber" : ann.source === "ai" ? "badge-violet" : "badge-dim"}`}>{ann.source}</span></td>
                          <td>
                            <span className={`badge ${ann.confirmed ? "badge-emerald" : "badge-warn"}`}>
                              {ann.confirmed ? "已确认" : "待确认"}
                            </span>
                          </td>
                          <td>
                            {!ann.confirmed && (
                              <div className="row gap-xs">
                                <button className="btn btn-ghost btn-sm" style={{ fontSize: 10, padding: "2px 6px", color: "var(--emerald)" }}
                                  onClick={() => handleConfirm(ann, true)}>
                                  确认
                                </button>
                                <button className="btn btn-ghost btn-sm" style={{ fontSize: 10, padding: "2px 6px", color: "var(--coral)" }}
                                  onClick={() => handleConfirm(ann, false)}>
                                  驳回
                                </button>
                              </div>
                            )}
                          </td>
                        </tr>
                      );
                      })}
                    </tbody>
                  </table>
                ) : (
                  <div className="empty" style={{ padding: 24 }}>
                    <div className="empty-text">
                      {selectedDb ? "这个数据库还没有语义标注" : "请选择数据库查看语义标注"}
                    </div>
                  </div>
                )}
              </div>
              <div className="card-body" style={{ borderTop: "1px solid var(--border-0)" }}>
                <div className="flex-between">
                  <span className="field-label">
                    第 {annotationPage} / {annotationPageCount} 页，当前显示 {annotations.length} 条
                  </span>
                  <div className="row gap-sm">
                    <button
                      className="btn btn-ghost btn-sm"
                      disabled={annotationPage <= 1}
                      onClick={() => setAnnotationPage((p) => Math.max(1, p - 1))}
                    >
                      上一页
                    </button>
                    <button
                      className="btn btn-ghost btn-sm"
                      disabled={annotationPage >= annotationPageCount}
                      onClick={() => setAnnotationPage((p) => Math.min(annotationPageCount, p + 1))}
                    >
                      下一页
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* ════ SERVICES TAB ════ */}
        {tab === "services" && (
          <div className="fade-up">
            <div className="row gap-sm mb-md wrap">
              <input
                className="input"
                style={{ maxWidth: 320 }}
                placeholder="搜索服务、来源、路径或数据库"
                value={serviceQuery}
                onChange={(e) => setServiceQuery(e.target.value)}
              />
              <button className="btn btn-primary btn-sm" onClick={handleRefreshServices} disabled={refreshing}>
                {refreshing ? <><span className="spinner" /> 刷新中</> : "刷新服务"}
              </button>
            </div>
            {targetService && !services.some((svc) => svc.name === targetService) && (
              <div className="card mb-md" style={{ borderLeftColor: "var(--warn)", borderLeftWidth: 3 }}>
                <div className="card-body" style={{ fontSize: 12, color: "var(--warn)", lineHeight: 1.7 }}>
                  Probe 链路中出现了服务 <span className="mono">{targetService}</span>，但 Atlas 当前服务发现结果里没有对应条目。
                  这通常表示 Atlas 的服务发现尚未采集到业务服务，或服务名和日志进程名不完全一致。
                </div>
              </div>
            )}
            <div className="card">
              <div className="card-head">
                <h3>已发现服务</h3>
                <span className="badge badge-teal">{filteredServices.length}/{services.length}</span>
              </div>
              <div className="card-body flush" style={{ overflowX: "auto" }}>
                {filteredServices.length > 0 ? (
                  <table className="dtable">
                    <thead>
                      <tr>
                        <th>名称</th>
                        <th>状态</th>
                        <th>来源</th>
                        <th>PID</th>
                        <th>部署路径</th>
                        <th>日志路径</th>
                        <th>数据库</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredServices.map((svc) => (
                        <tr key={svc.name} style={params.get("svc") === svc.name ? { background: "var(--amber-glow)" } : undefined}>
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
                          <td className="mono truncate" style={{ maxWidth: 200, fontSize: 11 }}>{svc.deploy_path || "\u2014"}</td>
                          <td className="mono truncate" style={{ maxWidth: 200, fontSize: 11 }}>{svc.log_path || "\u2014"}</td>
                          <td>
                            <div className="row gap-xs wrap">
                              {serviceDatabases(svc).length > 0
                                ? serviceDatabases(svc).map((d) => (
                                  <span key={d} className="badge badge-dim" style={{ cursor: "pointer" }}
                                    onClick={() => { setSelectedDb(d); setTab("schemas"); }}>{d}</span>
                                ))
                                : "\u2014"}
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : (
                  <div className="empty" style={{ padding: 28 }}>
                    <div className="empty-icon">{"\u2B22"}</div>
                    <div className="empty-text">
                      {services.length > 0 ? "没有匹配的服务" : "还没有发现服务，请刷新或检查 supervisor / Probe 日志来源配置"}
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </>
  );
}
