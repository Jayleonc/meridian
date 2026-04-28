import { useEffect, useState } from "react";
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

type Tab = "schemas" | "services" | "annotations";

export default function AtlasPage() {
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") as Tab) || "schemas";
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

  // Annotation state
  const [annotations, setAnnotations] = useState<Annotation[]>([]);
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

  // When db is selected, load its tables
  useEffect(() => {
    if (selectedDb) {
      loadTables(selectedDb);
      loadAnnotations(selectedDb);
    }
  }, [selectedDb]);

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
    try {
      const r = await atlas.listAnnotations(db);
      setAnnotations(r.annotations);
    } catch {
      setAnnotations([]);
    }
  }

  async function selectTable(db: string, tableName: string) {
    setTableLoading(true);
    try {
      const detail = await atlas.getTable(db, tableName);
      setSelectedTable(detail);
    } catch {
      toast("error", `Failed to load table ${tableName}`);
    }
    setTableLoading(false);
  }

  async function handleCollect() {
    setCollecting(true);
    try {
      const r = await atlas.collectSchema(selectedDb || undefined);
      toast("success", `Collected ${r.collected} database(s)`);
      await loadDatabases();
      if (selectedDb) await loadTables(selectedDb);
    } catch (e) {
      toast("error", e instanceof Error ? e.message : "Collection failed");
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
      toast("success", `Annotated ${annotateCol}`);
      setAnnotateSemantic("");
      if (annotateDb === selectedDb) await loadAnnotations(selectedDb);
    } catch (e) {
      toast("error", e instanceof Error ? e.message : "Annotation failed");
    }
    setAnnotating(false);
  }

  async function handleConfirm(ann: Annotation, confirmed: boolean) {
    try {
      await atlas.confirmAnnotation({
        database: ann.database,
        table: ann.table,
        column: ann.column,
        confirmed,
      });
      toast("success", confirmed ? "Confirmed" : "Rejected");
      await loadAnnotations(ann.database);
    } catch {
      toast("error", "Failed");
    }
  }

  async function handleSearch() {
    if (!searchQuery.trim()) return;
    try {
      const r = await atlas.searchMeta(searchQuery.trim());
      setSearchResult({ matched_table: r.matched_table, matched_column: r.matched_column });
    } catch {
      toast("error", "Search failed");
    }
  }

  async function handleRefreshServices() {
    setRefreshing(true);
    try {
      const r = await atlas.refreshServices();
      setServices(r.service);
      toast("success", `Found ${r.count} services`);
    } catch {
      toast("error", "Refresh failed");
    }
    setRefreshing(false);
  }

  function setTab(t: Tab) {
    setParams({ tab: t, ...(selectedDb ? { db: selectedDb } : {}) });
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
              {collecting ? <><span className="spinner" /> Collecting</> : "Collect Schema"}
            </button>
          </div>
        </div>
        <div className="page-toolbar">
          <div className="tab-bar">
            <button className={`tab-btn ${tab === "schemas" ? "active" : ""}`} onClick={() => setTab("schemas")}>
              Schema Browser
            </button>
            <button className={`tab-btn ${tab === "annotations" ? "active" : ""}`} onClick={() => setTab("annotations")}>
              Annotations
              {annotations.filter((a) => !a.confirmed).length > 0 && (
                <span className="tab-count">{annotations.filter((a) => !a.confirmed).length}</span>
              )}
            </button>
            <button className={`tab-btn ${tab === "services" ? "active" : ""}`} onClick={() => setTab("services")}>
              Services ({services.length})
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
                  <h3>Databases</h3>
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
                        <span className="badge badge-dim">{db.table_count} tables</span>
                        <span className="badge badge-dim">{db.snapshot_count} snaps</span>
                      </div>
                    </div>
                  )) : (
                    <div className="empty" style={{ padding: 20 }}>
                      <div className="empty-text">No databases. Click "Collect Schema" above.</div>
                    </div>
                  )}
                </div>
              </div>

              {/* Table list */}
              {selectedDb && (
                <div className="card fade-up stagger-1" style={{ flex: 1, display: "flex", flexDirection: "column" }}>
                  <div className="card-head">
                    <h3>Tables in {selectedDb}</h3>
                    <span className="badge badge-teal">{tables.length}</span>
                  </div>
                  <div className="card-body flush" style={{ flex: 1, overflowY: "auto" }}>
                    {tables.map((t) => (
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
                          <span style={{ fontSize: 11, color: "var(--t4)" }}>{t.column_count} cols</span>
                          {t.row_count_approx > 0 && (
                            <span style={{ fontSize: 11, color: "var(--t4)" }}>~{t.row_count_approx.toLocaleString()} rows</span>
                          )}
                        </div>
                        {t.comment && (
                          <div style={{ fontSize: 11, color: "var(--t3)", marginTop: 2 }}>{t.comment}</div>
                        )}
                      </div>
                    ))}
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
                  placeholder="Search tables, columns, comments..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && handleSearch()}
                />
                <button className="btn btn-primary btn-sm" onClick={handleSearch} disabled={!searchQuery.trim()}>
                  Search
                </button>
              </div>

              {/* Search results */}
              {searchResult && (
                <div className="card mb-md fade-up">
                  <div className="card-head">
                    <h3>Search Results</h3>
                    <button className="btn btn-ghost btn-sm" onClick={() => setSearchResult(null)}>Clear</button>
                  </div>
                  <div className="card-body">
                    {searchResult.matched_table.length > 0 && (
                      <div className="mb-md">
                        <div className="field-label mb-sm">Matched Tables ({searchResult.matched_table.length})</div>
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
                        <div className="field-label mb-sm">Matched Columns ({searchResult.matched_column.length})</div>
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
                        <div className="empty-text">No matches found</div>
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
                        <span className="badge badge-dim">~{selectedTable.row_count_approx.toLocaleString()} rows</span>
                      )}
                    </div>
                    <button
                      className="btn btn-ghost btn-sm"
                      onClick={() =>
                        inv.push({
                          type: "entity",
                          label: `Query ${selectedTable.name}`,
                          path: "/lens",
                          data: { database: selectedTable.database, table: selectedTable.name },
                        })
                      }
                    >
                      Query in Lens
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
                          <th>Column</th>
                          <th>Type</th>
                          <th>Nullable</th>
                          <th>Key</th>
                          <th>Comment</th>
                          <th>Semantic</th>
                          <th>Actions</th>
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
                                <span style={{ color: "var(--t4)", fontSize: 11 }}>none</span>
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
                                Annotate
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
                  <div className="card-body"><div className="empty"><div className="empty-text">Loading...</div></div></div>
                </div>
              ) : (
                <div className="card fade-up">
                  <div className="card-body">
                    <div className="empty" style={{ height: 300 }}>
                      <div className="empty-icon">{"\u2637"}</div>
                      <div className="empty-text">Select a table from the left to view its structure</div>
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
              <div className="card-head"><h3>Add Semantic Annotation</h3></div>
              <div className="card-body">
                <div className="row gap-sm mb-sm">
                  <div style={{ flex: 1 }}>
                    <div className="field-label mb-sm">Database</div>
                    <select className="input" value={annotateDb} onChange={(e) => setAnnotateDb(e.target.value)}>
                      <option value="">select...</option>
                      {databases.map((d) => <option key={d.database} value={d.database}>{d.database}</option>)}
                    </select>
                  </div>
                  <div style={{ flex: 1 }}>
                    <div className="field-label mb-sm">Table</div>
                    <input className="input" value={annotateTable} onChange={(e) => setAnnotateTable(e.target.value)} placeholder="table_name" />
                  </div>
                  <div style={{ flex: 1 }}>
                    <div className="field-label mb-sm">Column</div>
                    <input className="input" value={annotateCol} onChange={(e) => setAnnotateCol(e.target.value)} placeholder="column_name" />
                  </div>
                </div>
                <div className="row gap-sm">
                  <div style={{ flex: 1 }}>
                    <div className="field-label mb-sm">Semantic Description</div>
                    <input
                      className="input"
                      value={annotateSemantic}
                      onChange={(e) => setAnnotateSemantic(e.target.value)}
                      placeholder="e.g. user's phone number, order creation time..."
                      onKeyDown={(e) => e.key === "Enter" && handleAnnotate()}
                    />
                  </div>
                  <div style={{ paddingTop: 22 }}>
                    <button className="btn btn-primary" onClick={handleAnnotate} disabled={annotating || !annotateDb || !annotateTable || !annotateCol || !annotateSemantic}>
                      {annotating ? <><span className="spinner" /> Saving</> : "Save"}
                    </button>
                  </div>
                </div>
              </div>
            </div>

            {/* Existing annotations */}
            <div className="card">
              <div className="card-head">
                <h3>
                  Annotations
                  {selectedDb && <span style={{ color: "var(--teal)", marginLeft: 6, textTransform: "none" }}>({selectedDb})</span>}
                </h3>
                <div className="row gap-sm">
                  <select className="input" style={{ width: 160 }} value={selectedDb} onChange={(e) => setSelectedDb(e.target.value)}>
                    <option value="">select database...</option>
                    {databases.map((d) => <option key={d.database} value={d.database}>{d.database}</option>)}
                  </select>
                  <span className="badge badge-teal">{annotations.length}</span>
                </div>
              </div>
              <div className="card-body flush" style={{ maxHeight: 500, overflowY: "auto" }}>
                {annotations.length > 0 ? (
                  <table className="dtable">
                    <thead>
                      <tr>
                        <th>Table.Column</th>
                        <th>Semantic</th>
                        <th>Source</th>
                        <th>Status</th>
                        <th>Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {annotations.map((ann, i) => (
                        <tr key={i}>
                          <td className="mono">{ann.table}.{ann.column}</td>
                          <td style={{ color: "var(--teal)" }}>{ann.semantic}</td>
                          <td><span className={`badge ${ann.source === "manual" ? "badge-amber" : ann.source === "ai" ? "badge-violet" : "badge-dim"}`}>{ann.source}</span></td>
                          <td>
                            <span className={`badge ${ann.confirmed ? "badge-emerald" : "badge-warn"}`}>
                              {ann.confirmed ? "confirmed" : "pending"}
                            </span>
                          </td>
                          <td>
                            {!ann.confirmed && (
                              <div className="row gap-xs">
                                <button className="btn btn-ghost btn-sm" style={{ fontSize: 10, padding: "2px 6px", color: "var(--emerald)" }}
                                  onClick={() => handleConfirm(ann, true)}>
                                  Confirm
                                </button>
                                <button className="btn btn-ghost btn-sm" style={{ fontSize: 10, padding: "2px 6px", color: "var(--coral)" }}
                                  onClick={() => handleConfirm(ann, false)}>
                                  Reject
                                </button>
                              </div>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : (
                  <div className="empty" style={{ padding: 24 }}>
                    <div className="empty-text">
                      {selectedDb ? "No annotations for this database" : "Select a database to view annotations"}
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

        {/* ════ SERVICES TAB ════ */}
        {tab === "services" && (
          <div className="fade-up">
            <div className="row gap-sm mb-md">
              <button className="btn btn-primary btn-sm" onClick={handleRefreshServices} disabled={refreshing}>
                {refreshing ? <><span className="spinner" /> Refreshing</> : "Refresh Services"}
              </button>
            </div>
            <div className="card">
              <div className="card-head">
                <h3>Discovered Services</h3>
                <span className="badge badge-teal">{services.length}</span>
              </div>
              <div className="card-body flush" style={{ overflowX: "auto" }}>
                {services.length > 0 ? (
                  <table className="dtable">
                    <thead>
                      <tr><th>Name</th><th>Status</th><th>PID</th><th>Deploy Path</th><th>Log Path</th><th>Databases</th></tr>
                    </thead>
                    <tbody>
                      {services.map((svc) => (
                        <tr key={svc.name} style={params.get("svc") === svc.name ? { background: "var(--amber-glow)" } : undefined}>
                          <td className="mono">{svc.name}</td>
                          <td><span className={`badge ${svc.status === "RUNNING" ? "badge-emerald" : "badge-coral"}`}>{svc.status}</span></td>
                          <td className="mono">{svc.pid || "\u2014"}</td>
                          <td className="mono truncate" style={{ maxWidth: 200, fontSize: 11 }}>{svc.deploy_path || "\u2014"}</td>
                          <td className="mono truncate" style={{ maxWidth: 200, fontSize: 11 }}>{svc.log_path || "\u2014"}</td>
                          <td>
                            <div className="row gap-xs wrap">
                              {svc.databases?.map((d) => (
                                <span key={d} className="badge badge-dim" style={{ cursor: "pointer" }}
                                  onClick={() => { setSelectedDb(d); setTab("schemas"); }}>{d}</span>
                              )) ?? "\u2014"}
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : (
                  <div className="empty"><div className="empty-icon">{"\u2B22"}</div><div className="empty-text">No services found</div></div>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </>
  );
}
