import { useEffect, useState } from "react";
import { useApp } from "../../context/AppContext";
import { useInvestigation } from "../../context/InvestigationContext";
import { useQueryHistory } from "../../hooks/useQueryHistory";
import {
  atlas,
  lens,
  type EntitySummary,
  type EntityDetail,
  type QueryResult,
  type FilterCondition,
} from "../../api/client";

export default function LensPage() {
  const { toast } = useApp();
  const inv = useInvestigation();
  const { history, push: pushHistory, clear: clearHistory } = useQueryHistory();

  const [entities, setEntities] = useState<EntitySummary[]>([]);
  const [selected, setSelected] = useState<EntityDetail | null>(null);
  const [entityLoading, setEntityLoading] = useState(false);
  const [error, setError] = useState("");
  const [atlasDatabases, setAtlasDatabases] = useState<Array<{ database: string; table_count: number }>>([]);

  // Query state
  const [activeEntity, setActiveEntity] = useState("");
  const [filters, setFilters] = useState<Array<{ field: string; op: string; value: string }>>([]);
  const [selectedFields, setSelectedFields] = useState<string[]>([]);
  const [orderBy, setOrderBy] = useState("");
  const [limit, setLimit] = useState(20);
  const [result, setResult] = useState<QueryResult | null>(null);
  const [queryLoading, setQueryLoading] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [showSql, setShowSql] = useState(false);
  const [importing, setImporting] = useState(false);

  useEffect(() => {
    void loadEntities();
    atlas.listDatabases()
      .then((r) => setAtlasDatabases(r.databases))
      .catch(() => setAtlasDatabases([]));
  }, []);

  async function loadEntities() {
    try {
      const r = await lens.listEntities();
      setEntities(r.entity);
      setError("");
      return r.entity;
    } catch {
      setError("Lens is offline");
      return [];
    }
  }

  async function handleImportFromAtlas() {
    setImporting(true);
    try {
      const r = await lens.importFromAtlas();
      if (r.imported > 0) {
        toast("success", `Imported ${r.imported} entities from Atlas (${r.skipped} skipped)`);
        await loadEntities();
      } else if (r.skipped > 0) {
        toast("info", `All ${r.skipped} entities already exist. Use overwrite to update.`);
      } else {
        toast("info", r.errors.length > 0 ? r.errors[0] : "No tables found in Atlas");
      }
    } catch (e) {
      toast("error", e instanceof Error ? e.message : "Import failed — is Atlas running?");
    }
    setImporting(false);
  }

  async function handleDeleteEntity(name: string) {
    try {
      await lens.deleteEntity(name);
      toast("success", `Deleted ${name}`);
      if (activeEntity === name) {
        setSelected(null);
        setActiveEntity("");
        setResult(null);
      }
      await loadEntities();
    } catch {
      toast("error", "Delete failed");
    }
  }

  async function selectEntity(name: string) {
    setEntityLoading(true);
    setError("");
    try {
      const detail = await lens.describeEntity(name);
      setSelected(detail);
      setActiveEntity(name);
      setFilters([]);
      setSelectedFields([]);
      setOrderBy("");
      setResult(null);
      setShowSql(false);
    } catch {
      toast("error", `Failed to load entity: ${name}`);
    }
    setEntityLoading(false);
  }

  // ── Filter management ──
  function addFilter() {
    setFilters([...filters, { field: "", op: "eq", value: "" }]);
  }

  function updateFilter(i: number, key: string, val: string) {
    const copy = [...filters];
    copy[i] = { ...copy[i], [key]: val };
    setFilters(copy);
  }

  function removeFilter(i: number) {
    setFilters(filters.filter((_, idx) => idx !== i));
  }

  // ── Field toggle ──
  function toggleField(name: string) {
    setSelectedFields((prev) =>
      prev.includes(name) ? prev.filter((f) => f !== name) : [...prev, name]
    );
  }

  // ── Execute query ──
  async function executeQuery() {
    if (!activeEntity) return;
    setQueryLoading(true);
    setError("");

    const validFilters: FilterCondition[] = filters
      .filter((f) => f.field && f.value)
      .map((f) => ({
        field: f.field,
        op: f.op,
        value: f.op === "in" ? f.value.split(",").map((s) => s.trim()) : f.value,
      }));

    const dsl = {
      entity: activeEntity,
      filter: validFilters.length > 0 ? validFilters : undefined,
      field: selectedFields.length > 0 ? selectedFields : undefined,
      order_by: orderBy || undefined,
      limit,
    };

    try {
      const r = await lens.query(dsl);
      setResult(r);

      pushHistory({
        entity: activeEntity,
        dsl,
        resultCount: r.count,
        durationMs: r.duration_ms,
      });

      if (r.success) {
        inv.push({
          type: "query",
          label: `${activeEntity} (${r.count} rows)`,
          path: `/lens`,
          data: { entity: activeEntity },
        });
      }
    } catch (e) {
      toast("error", e instanceof Error ? e.message : "Query failed");
    }
    setQueryLoading(false);
  }

  // ── Load from history ──
  function loadFromHistory(entry: { entity: string; dsl: Record<string, unknown> }) {
    setShowHistory(false);
    const dsl = entry.dsl as {
      filter?: Array<{ field: string; op: string; value: unknown }>;
      field?: string[];
      order_by?: string;
      limit?: number;
    };

    selectEntity(entry.entity).then(() => {
      if (dsl.filter) {
        setFilters(
          dsl.filter.map((f) => ({
            field: f.field,
            op: f.op,
            value: Array.isArray(f.value) ? f.value.join(", ") : String(f.value),
          }))
        );
      }
      if (dsl.field) setSelectedFields(dsl.field);
      if (dsl.order_by) setOrderBy(dsl.order_by);
      if (dsl.limit) setLimit(dsl.limit);
    });
  }

  const fieldNames = selected ? Object.keys(selected.fields) : [];
  const filterableFields = selected
    ? fieldNames.filter((n) => selected.fields[n]?.filterable)
    : [];
  const sortableFields = selected
    ? fieldNames.filter((n) => selected.fields[n]?.sortable)
    : [];
  const atlasSummary = atlasDatabases.length > 0
    ? `Atlas has ${atlasDatabases.map((db) => `${db.database} (${db.table_count} tables)`).join(", ")}.`
    : "";

  return (
    <>
      <div className="page-header">
        <div className="flex-between">
          <div>
            <h2>Lens</h2>
            <div className="page-desc">数据查询 — 业务实体映射与结构化查询</div>
          </div>
          <div className="row gap-sm">
            <button className="btn btn-ghost btn-sm" onClick={() => setShowHistory(!showHistory)}>
              History {history.length > 0 && <span className="badge badge-dim" style={{ marginLeft: 4 }}>{history.length}</span>}
            </button>
            <button className="btn btn-primary btn-sm" onClick={handleImportFromAtlas} disabled={importing}>
              {importing ? <><span className="spinner" /> Importing</> : "Import from Atlas"}
            </button>
          </div>
        </div>
      </div>

      <div className="page-body" style={{ display: "flex", gap: 14, overflow: "hidden", padding: "14px 28px 28px" }}>
        {/* ── Entity list panel ── */}
        <div style={{ width: 240, flexShrink: 0, display: "flex", flexDirection: "column" }}>
          <div className="card fade-up" style={{ flex: 1, display: "flex", flexDirection: "column" }}>
            <div className="card-head">
              <h3>Entities</h3>
              <span className="badge badge-teal">{entities.length}</span>
            </div>
            <div className="card-body flush" style={{ flex: 1, overflowY: "auto" }}>
              {entities.length > 0 ? (
                entities.map((e) => (
                  <div
                    key={e.name}
                    onClick={() => selectEntity(e.name)}
                    style={{
                      padding: "10px 14px",
                      borderBottom: "1px solid var(--border-0)",
                      cursor: "pointer",
                      background: activeEntity === e.name ? "var(--amber-glow)" : "transparent",
                      transition: "background 0.15s",
                    }}
                    onMouseEnter={(ev) => {
                      if (activeEntity !== e.name)
                        ev.currentTarget.style.background = "rgba(255,255,255,0.02)";
                    }}
                    onMouseLeave={(ev) => {
                      if (activeEntity !== e.name) ev.currentTarget.style.background = "transparent";
                    }}
                  >
                    <div style={{ fontFamily: "var(--font-display)", fontWeight: 500, fontSize: 13 }}>
                      {e.display_name || e.name}
                    </div>
                    <div className="row gap-xs mt-xs" style={{ justifyContent: "space-between" }}>
                      <div className="row gap-xs">
                        <span className="badge badge-dim">{e.db_type}</span>
                        <span className="badge badge-dim">{e.field_count}f</span>
                      </div>
                      <button
                        className="btn btn-ghost btn-sm"
                        style={{ fontSize: 9, padding: "1px 5px", color: "var(--coral)", opacity: 0.5 }}
                        onClick={(ev) => { ev.stopPropagation(); handleDeleteEntity(e.name); }}
                        title="Delete entity"
                      >
                        {"\u2715"}
                      </button>
                    </div>
                  </div>
                ))
              ) : (
                <div className="empty" style={{ padding: 24 }}>
                  <div className="empty-text">
                    {error || `No entities. ${atlasSummary || "Atlas schema is not loaded yet."} Click "Import from Atlas" to auto-generate query entities.`}
                  </div>
                  <div className="row gap-sm mt-md" style={{ justifyContent: "center" }}>
                    <button className="btn btn-primary btn-sm" onClick={handleImportFromAtlas} disabled={importing}>
                      {importing ? "Importing..." : "Import from Atlas"}
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* ── Main workspace ── */}
        <div style={{ flex: 1, overflowY: "auto", minWidth: 0 }}>
          {showHistory && (
            <div className="card mb-md fade-up">
              <div className="card-head">
                <h3>Query History</h3>
                <button className="btn btn-danger btn-sm" onClick={clearHistory}>Clear</button>
              </div>
              <div className="card-body flush" style={{ maxHeight: 200, overflowY: "auto" }}>
                {history.length > 0 ? (
                  history.map((entry, i) => (
                    <div
                      key={i}
                      className="log-line clickable"
                      onClick={() => loadFromHistory(entry)}
                    >
                      <span className="log-ts" style={{ width: "auto" }}>
                        {new Date(entry.timestamp).toLocaleTimeString()}
                      </span>
                      <span style={{ color: "var(--teal)", fontFamily: "var(--font-mono)", fontSize: 12 }}>
                        {entry.entity}
                      </span>
                      {entry.resultCount !== undefined && (
                        <span className="badge badge-dim">{entry.resultCount} rows</span>
                      )}
                      {entry.durationMs !== undefined && (
                        <span style={{ color: "var(--t4)", fontSize: 11 }}>{entry.durationMs}ms</span>
                      )}
                    </div>
                  ))
                ) : (
                  <div className="empty" style={{ padding: 16 }}>
                    <div className="empty-text">No query history</div>
                  </div>
                )}
              </div>
            </div>
          )}

          {selected ? (
            <div className="fade-up">
              {/* Entity info */}
              <div className="card mb-md">
                <div className="card-head">
                  <div className="row gap-sm">
                    <h3 style={{ textTransform: "none", letterSpacing: 0, fontSize: 13 }}>
                      {selected.display_name || selected.name}
                    </h3>
                    <span className="badge badge-teal">{selected.db_type}</span>
                    {selected.datasource && <span className="badge badge-dim">{selected.datasource}</span>}
                  </div>
                  <span style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--t4)" }}>
                    {selected.database}.{selected.primary_table}
                  </span>
                </div>
                <div className="card-body flush" style={{ maxHeight: 200, overflowY: "auto" }}>
                  <table className="dtable">
                    <thead>
                      <tr>
                        <th>Field</th>
                        <th>Type</th>
                        <th>Semantic</th>
                        <th style={{ textAlign: "center" }}>Filter</th>
                        <th style={{ textAlign: "center" }}>Sort</th>
                        <th style={{ textAlign: "center" }}>Sensitive</th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.values(selected.fields).map((f) => (
                        <tr key={f.name}>
                          <td className="mono">{f.name}</td>
                          <td><span className="badge badge-dim">{f.type || "string"}</span></td>
                          <td style={{ color: f.semantic ? "var(--teal)" : "var(--t4)", fontSize: 12 }}>
                            {f.semantic || "\u2014"}
                          </td>
                          <td style={{ textAlign: "center" }}>{f.filterable ? "\u2713" : ""}</td>
                          <td style={{ textAlign: "center" }}>{f.sortable ? "\u2713" : ""}</td>
                          <td style={{ textAlign: "center" }}>
                            {f.sensitive && <span className="badge badge-coral">yes</span>}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Query builder */}
              <div className="card mb-md">
                <div className="card-head">
                  <h3>Query Builder</h3>
                  <div className="row gap-sm">
                    <button className="btn btn-ghost btn-sm" onClick={addFilter}>+ Filter</button>
                    <button
                      className="btn btn-primary btn-sm"
                      onClick={executeQuery}
                      disabled={queryLoading}
                    >
                      {queryLoading ? <><span className="spinner" /> Running</> : "\u25B6 Execute"}
                    </button>
                  </div>
                </div>
                <div className="card-body">
                  {/* Filters */}
                  {filters.length > 0 && (
                    <div className="mb-md">
                      <div className="field-label mb-sm">Filters</div>
                      {filters.map((f, i) => (
                        <div key={i} className="row gap-sm mb-sm">
                          <select className="input" style={{ width: 150 }} value={f.field} onChange={(e) => updateFilter(i, "field", e.target.value)}>
                            <option value="">field...</option>
                            {filterableFields.map((n) => <option key={n} value={n}>{n}</option>)}
                          </select>
                          <select className="input" style={{ width: 90 }} value={f.op} onChange={(e) => updateFilter(i, "op", e.target.value)}>
                            {["eq", "ne", "gt", "gte", "lt", "lte", "in", "like", "between"].map((op) => (
                              <option key={op} value={op}>{op}</option>
                            ))}
                          </select>
                          <input
                            className="input"
                            style={{ flex: 1 }}
                            placeholder={f.op === "in" ? "val1, val2, ..." : f.op === "between" ? "start,end" : "value..."}
                            value={f.value}
                            onChange={(e) => updateFilter(i, "value", e.target.value)}
                            onKeyDown={(e) => e.key === "Enter" && executeQuery()}
                          />
                          <button className="btn btn-ghost btn-sm" style={{ color: "var(--coral)", padding: "4px 8px" }} onClick={() => removeFilter(i)}>
                            {"\u2715"}
                          </button>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Fields */}
                  <div className="mb-md">
                    <div className="field-label mb-sm">
                      Fields {selectedFields.length > 0 && `(${selectedFields.length})`}
                    </div>
                    <div className="row gap-xs wrap">
                      {fieldNames.map((n) => {
                        const active = selectedFields.includes(n);
                        const isSensitive = selected.fields[n]?.sensitive;
                        return (
                          <button
                            key={n}
                            className={`badge ${active ? "badge-teal" : "badge-dim"}`}
                            style={{ cursor: "pointer", border: "none", opacity: isSensitive && !active ? 0.5 : 1 }}
                            onClick={() => toggleField(n)}
                            title={isSensitive ? "Sensitive field - will be masked" : undefined}
                          >
                            {isSensitive ? "\uD83D\uDD12 " : ""}{n}
                          </button>
                        );
                      })}
                    </div>
                    {selectedFields.length === 0 && (
                      <div style={{ fontSize: 11, color: "var(--t4)", marginTop: 4 }}>
                        All default_visible fields will be returned
                      </div>
                    )}
                  </div>

                  {/* Order & Limit */}
                  <div className="row gap-md">
                    <div style={{ flex: 1 }}>
                      <div className="field-label mb-sm">Order By</div>
                      <select className="input" value={orderBy} onChange={(e) => setOrderBy(e.target.value)}>
                        <option value="">default</option>
                        {sortableFields.map((n) => (
                          <option key={n} value={n}>{n} ASC</option>
                        ))}
                        {sortableFields.map((n) => (
                          <option key={`${n}-desc`} value={`-${n}`}>{n} DESC</option>
                        ))}
                      </select>
                    </div>
                    <div style={{ width: 100 }}>
                      <div className="field-label mb-sm">Limit</div>
                      <input
                        className="input"
                        type="number"
                        value={limit}
                        onChange={(e) => setLimit(Math.max(1, Math.min(100, Number(e.target.value))))}
                        min={1}
                        max={100}
                      />
                    </div>
                  </div>
                </div>
              </div>

              {/* Results */}
              {result && (
                <div className="card fade-up">
                  <div className="card-head">
                    <h3>Results</h3>
                    <div className="row gap-sm">
                      {result.success ? (
                        <>
                          <span className="badge badge-emerald">{result.count} rows</span>
                          <span className="badge badge-dim">{result.duration_ms}ms</span>
                          {result.sql && (
                            <button
                              className="btn btn-ghost btn-sm"
                              onClick={() => setShowSql(!showSql)}
                            >
                              {showSql ? "Hide SQL" : "Show SQL"}
                            </button>
                          )}
                        </>
                      ) : (
                        <span className="badge badge-coral">Error</span>
                      )}
                    </div>
                  </div>

                  {showSql && result.sql && (
                    <div style={{
                      padding: "10px 16px",
                      background: "var(--base)",
                      fontFamily: "var(--font-mono)",
                      fontSize: 12,
                      color: "var(--t3)",
                      borderBottom: "1px solid var(--border-0)",
                      overflowX: "auto",
                      whiteSpace: "pre-wrap",
                      lineHeight: 1.6,
                    }}>
                      {result.sql}
                    </div>
                  )}

                  <div className="card-body flush" style={{ overflowX: "auto", maxHeight: 400 }}>
                    {result.success && result.data && result.data.length > 0 ? (
                      <table className="dtable">
                        <thead>
                          <tr>
                            {Object.keys(result.data[0]).map((col) => (
                              <th key={col}>{col}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {result.data.map((row, i) => (
                            <tr key={i}>
                              {Object.values(row).map((val, j) => (
                                <td key={j} className="mono" style={{ fontSize: 12 }}>
                                  {val === null ? (
                                    <span style={{ color: "var(--t4)" }}>NULL</span>
                                  ) : (
                                    String(val)
                                  )}
                                </td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    ) : result.error ? (
                      <div style={{ padding: 16, color: "var(--coral)", fontFamily: "var(--font-mono)", fontSize: 12 }}>
                        {result.error}
                      </div>
                    ) : (
                      <div className="empty">
                        <div className="empty-text">No results returned</div>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="card fade-up" style={{ height: "100%" }}>
              <div className="card-body">
                <div className="empty" style={{ height: 300 }}>
                  <div className="empty-icon">{"\u25C8"}</div>
                  <div className="empty-text">
                    {entityLoading ? "Loading..." : "Select an entity to explore and query"}
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </>
  );
}
