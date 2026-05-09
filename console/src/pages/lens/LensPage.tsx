import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
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
  type TableSummary,
} from "../../api/client";

export default function LensPage() {
  const [params] = useSearchParams();
  const { toast } = useApp();
  const inv = useInvestigation();
  const { history, push: pushHistory, clear: clearHistory } = useQueryHistory();

  const [entities, setEntities] = useState<EntitySummary[]>([]);
  const [selected, setSelected] = useState<EntityDetail | null>(null);
  const [entityLoading, setEntityLoading] = useState(false);
  const [error, setError] = useState("");
  const [atlasDatabases, setAtlasDatabases] = useState<Array<{ database: string; table_count: number }>>([]);
  const [showImportPanel, setShowImportPanel] = useState(false);
  const [importDatabase, setImportDatabase] = useState("");
  const [atlasTables, setAtlasTables] = useState<TableSummary[]>([]);
  const [importTableQuery, setImportTableQuery] = useState("");
  const [selectedImportTables, setSelectedImportTables] = useState<string[]>([]);
  const [loadingAtlasTables, setLoadingAtlasTables] = useState(false);
  const [entityQuery, setEntityQuery] = useState("");
  const [entityDatabase, setEntityDatabase] = useState("");
  const [entityMenu, setEntityMenu] = useState("");
  const [selectedEntityNames, setSelectedEntityNames] = useState<string[]>([]);
  const [fieldQuery, setFieldQuery] = useState("");

  // Query state
  const [activeEntity, setActiveEntity] = useState("");
  const [filters, setFilters] = useState<Array<{ field: string; op: string; value: string }>>([]);
  const [selectedFields, setSelectedFields] = useState<string[]>([]);
  const [orderBy, setOrderBy] = useState("");
  const [limit, setLimit] = useState(20);
  const [queryMode, setQueryMode] = useState<"rows" | "count" | "preview">("rows");
  const [result, setResult] = useState<QueryResult | null>(null);
  const [queryLoading, setQueryLoading] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [showSql, setShowSql] = useState(false);
  const [importing, setImporting] = useState(false);
  const [savingEntity, setSavingEntity] = useState(false);

  useEffect(() => {
    void bootLens();
    atlas.listDatabases()
      .then((r) => setAtlasDatabases(r.databases))
      .catch(() => setAtlasDatabases([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function bootLens() {
    const list = await loadEntities();
    const db = params.get("db") || "";
    const table = params.get("table") || "";
    const target = params.get("entity") || (db && table ? `${db}__${table}` : "");
    if (!target) return;

    const exists = list.some((entity) => entity.name === target);
    if (!exists) {
      setEntityQuery(table || target);
      return;
    }

    await selectEntity(target);
    if (params.get("action") === "count") {
      setQueryMode("count");
      setFilters([]);
      setSelectedFields([]);
      setOrderBy("");
      void executeQuery({ entity: target, mode: "count", filters: [], fields: [], orderBy: "", limit: 1 });
    }
  }

  async function loadEntities() {
    try {
      const r = await lens.listEntities(true);
      setEntities(r.entity);
      setSelectedEntityNames((current) =>
        current.filter((name) => r.entity.some((entity) => entity.name === name))
      );
      setError("");
      return r.entity;
    } catch {
      setError("Lens 服务离线");
      return [];
    }
  }

  async function handleImportFromAtlas() {
    if (!importDatabase) {
      toast("info", "先选择一个数据库");
      return;
    }
    if (selectedImportTables.length === 0) {
      toast("info", "至少选择一张表，避免一次性导入过多实体");
      return;
    }
    setImporting(true);
    try {
      const r = await lens.importFromAtlas({
        database: importDatabase,
        tables: selectedImportTables,
        enabled: false,
      });
      if (r.imported > 0) {
        toast("success", `已导入 ${r.imported} 个草稿实体，确认后 Agent 才能使用`);
        setSelectedImportTables([]);
        await loadEntities();
      } else if (r.skipped > 0) {
        toast("info", `${r.skipped} 个实体已存在；需要更新时再使用覆盖导入`);
      } else {
        toast("info", r.errors.length > 0 ? r.errors[0] : "Atlas 暂未提供可导入的表");
      }
    } catch (e) {
      toast("error", e instanceof Error ? e.message : "导入失败，请确认 Atlas 已运行");
    }
    setImporting(false);
  }

  async function loadAtlasTables(database: string) {
    setImportDatabase(database);
    setSelectedImportTables([]);
    setAtlasTables([]);
    if (!database) return;

    setLoadingAtlasTables(true);
    try {
      const r = await atlas.listTables(database);
      setAtlasTables(r.tables);
    } catch {
      toast("error", "读取 Atlas 表列表失败");
    }
    setLoadingAtlasTables(false);
  }

  function toggleImportTable(name: string) {
    setSelectedImportTables((current) =>
      current.includes(name)
        ? current.filter((item) => item !== name)
        : [...current, name]
    );
  }

  function toggleEntitySelection(name: string) {
    setSelectedEntityNames((current) =>
      current.includes(name)
        ? current.filter((item) => item !== name)
        : [...current, name]
    );
  }

  function toggleCurrentEntities() {
    const currentNames = filteredEntities.map((entity) => entity.name);
    const allSelected = currentNames.length > 0 && currentNames.every((name) => selectedEntityNames.includes(name));
    setSelectedEntityNames((current) =>
      allSelected
        ? current.filter((name) => !currentNames.includes(name))
        : Array.from(new Set([...current, ...currentNames]))
    );
  }

  async function batchSetAgentVisibility(enabled: boolean) {
    if (selectedEntityNames.length === 0) return;
    setSavingEntity(true);
    try {
      await Promise.all(
        selectedEntityNames.map((name) => lens.updateEntity(name, { enabled }))
      );
      toast("success", enabled ? `已启用 ${selectedEntityNames.length} 个实体给 Agent` : `已将 ${selectedEntityNames.length} 个实体转为草稿`);
      setSelectedEntityNames([]);
      await loadEntities();
      if (selected) {
        const detail = await lens.describeEntity(selected.name);
        setSelected(detail);
      }
    } catch (e) {
      toast("error", e instanceof Error ? e.message : "批量操作失败");
    }
    setSavingEntity(false);
  }

  async function handleDeleteEntity(name: string) {
    if (!window.confirm(`确认删除 Lens 实体「${name}」？这只会删除 Lens 查询映射，不会删除业务表。`)) {
      return;
    }
    try {
      await lens.deleteEntity(name);
      toast("success", `已删除 ${name}`);
      if (activeEntity === name) {
        setSelected(null);
        setActiveEntity("");
        setResult(null);
      }
      setEntityMenu("");
      await loadEntities();
    } catch {
      toast("error", "删除失败");
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
      setQueryMode("rows");
      setResult(null);
      setShowSql(false);
      setEntityMenu("");
      setFieldQuery("");
    } catch {
      toast("error", `实体加载失败：${name}`);
    }
    setEntityLoading(false);
  }

  async function saveSelectedEntity(patch: Parameters<typeof lens.updateEntity>[1]) {
    if (!selected) return;
    setSavingEntity(true);
    try {
      const r = await lens.updateEntity(selected.name, patch);
      setSelected(r.entity);
      toast("success", r.entity.enabled ? "已启用，Agent 可以发现该实体" : "已保存为草稿，Agent 暂不可见");
      await loadEntities();
    } catch (e) {
      toast("error", e instanceof Error ? e.message : "保存失败");
    }
    setSavingEntity(false);
  }

  function patchField(name: string, patch: Partial<EntityDetail["fields"][string]>) {
    void saveSelectedEntity({ fields: { [name]: patch } });
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

  function addFieldFilter(field: string) {
    setFilters((current) => [...current, { field, op: "eq", value: "" }]);
  }

  // ── Field toggle ──
  function toggleField(name: string) {
    setSelectedFields((prev) =>
      prev.includes(name) ? prev.filter((f) => f !== name) : [...prev, name]
    );
  }

  // ── Execute query ──
  async function executeQuery(
    overrides: Partial<{
      mode: "rows" | "count" | "preview";
      entity: string;
      filters: Array<{ field: string; op: string; value: string }>;
      fields: string[];
      orderBy: string;
      limit: number;
    }> = {}
  ) {
    const targetEntity = overrides.entity ?? activeEntity;
    if (!targetEntity) return;
    setError("");

    const nextMode = overrides.mode ?? queryMode;
    const nextFilters = overrides.filters ?? filters;
    const nextFields = overrides.fields ?? selectedFields;
    const nextOrderBy = overrides.orderBy ?? orderBy;
    const nextLimit = overrides.limit ?? limit;

    const validFilters: FilterCondition[] = nextFilters
      .filter((f) => f.field && f.value)
      .map((f) => ({
        field: f.field,
        op: f.op,
        value: ["in", "between"].includes(f.op)
          ? f.value.split(",").map((s) => s.trim()).filter(Boolean)
          : f.value,
      }));

    if (nextMode === "rows" && validFilters.length === 0) {
      const message = "明细查询需要至少一个筛选条件，避免误扫生产业务表。";
      setResult({ success: false, error: message });
      toast("info", message);
      return;
    }

    setQueryLoading(true);

    const dsl = {
      entity: targetEntity,
      filter: validFilters.length > 0 ? validFilters : undefined,
      field: nextMode === "rows" && nextFields.length > 0 ? nextFields : undefined,
      aggregate: nextMode === "count" ? "count" as const : undefined,
      preview: nextMode === "preview" ? true : undefined,
      order_by: nextMode !== "count" ? nextOrderBy || undefined : undefined,
      limit: nextMode === "count" ? 1 : nextMode === "preview" ? Math.min(nextLimit, 20) : nextLimit,
    };

    try {
      const r = await lens.operatorQuery(dsl);
      setResult(r);

      pushHistory({
        entity: targetEntity,
        dsl,
        resultCount: r.count,
        durationMs: r.duration_ms,
      });

      if (r.success) {
        inv.push({
          type: "query",
          label: `${targetEntity} (${r.count} 行)`,
          path: `/lens`,
          data: { entity: targetEntity },
        });
      }
    } catch (e) {
      toast("error", e instanceof Error ? e.message : "查询失败");
    }
    setQueryLoading(false);
  }

  function applyDefaultFieldsTemplate() {
    if (!selected) return;
    const defaults = Object.values(selected.fields)
      .filter((field) => field.default_visible && !field.sensitive)
      .slice(0, 12)
      .map((field) => field.name);
    setQueryMode("rows");
    setSelectedFields(defaults);
    setResult(null);
  }

  function applyIdFilterTemplate() {
    const idField =
      filterableFields.find((field) => field === "id") ||
      filterableFields.find((field) => field.endsWith("_id")) ||
      filterableFields[0];
    if (!idField) {
      toast("info", "这个实体没有可筛选字段");
      return;
    }
    setQueryMode("rows");
    setFilters([{ field: idField, op: "eq", value: "" }]);
    setResult(null);
  }

  function runPreviewSample() {
    const timeField =
      selected?.constraint.time_field ||
      sortableFields.find((field) => /time|date|created|updated/i.test(field)) ||
      sortableFields[0] ||
      "";
    setQueryMode("preview");
    setFilters([]);
    setSelectedFields([]);
    setOrderBy(timeField ? `-${timeField}` : "");
    setLimit(20);
    setResult(null);
    void executeQuery({
      mode: "preview",
      filters: [],
      fields: [],
      orderBy: timeField ? `-${timeField}` : "",
      limit: 20,
    });
  }

  function runCountAll() {
    setQueryMode("count");
    setFilters([]);
    setSelectedFields([]);
    setOrderBy("");
    void executeQuery({ mode: "count", filters: [], fields: [], orderBy: "", limit: 1 });
  }

  // ── Load from history ──
  function loadFromHistory(entry: { entity: string; dsl: Record<string, unknown> }) {
    setShowHistory(false);
    const dsl = entry.dsl as {
      filter?: Array<{ field: string; op: string; value: unknown }>;
      field?: string[];
      aggregate?: "count";
      preview?: boolean;
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
      setQueryMode(dsl.aggregate === "count" ? "count" : dsl.preview ? "preview" : "rows");
      if (dsl.order_by) setOrderBy(dsl.order_by);
      if (dsl.limit) setLimit(dsl.limit);
    });
  }

  const fieldNames = selected ? Object.keys(selected.fields) : [];
  const filteredFieldNames = useMemo(() => {
    if (!selected) return [];
    const query = fieldQuery.trim().toLowerCase();
    if (!query) return fieldNames;
    return fieldNames.filter((name) => {
      const field = selected.fields[name];
      return [field.name, field.column, field.type, field.semantic]
        .filter(Boolean)
        .some((value) => value.toLowerCase().includes(query));
    });
  }, [selected, fieldNames, fieldQuery]);
  const filterableFields = selected
    ? fieldNames.filter((n) => selected.fields[n]?.filterable)
    : [];
  const sortableFields = selected
    ? fieldNames.filter((n) => selected.fields[n]?.sortable)
    : [];
  const atlasSummary = atlasDatabases.length > 0
    ? `Atlas 当前有 ${atlasDatabases.map((db) => `${db.database}（${db.table_count} 张表）`).join("、")}。`
    : "";
  const entityDatabases = useMemo(
    () => Array.from(new Set(entities.map((e) => e.database).filter(Boolean))).sort(),
    [entities]
  );
  const filteredEntities = useMemo(() => {
    const query = entityQuery.trim().toLowerCase();
    return entities.filter((e) => {
      const inDatabase = !entityDatabase || e.database === entityDatabase;
      if (!inDatabase) return false;
      if (!query) return true;
      return [e.name, e.display_name, e.database, e.db_type]
        .filter(Boolean)
        .some((value) => value.toLowerCase().includes(query));
    });
  }, [entities, entityQuery, entityDatabase]);
  const filteredAtlasTables = useMemo(() => {
    const query = importTableQuery.trim().toLowerCase();
    if (!query) return atlasTables;
    return atlasTables.filter((table) =>
      [table.name, table.comment, table.engine]
        .filter(Boolean)
        .some((value) => value.toLowerCase().includes(query))
    );
  }, [atlasTables, importTableQuery]);
  const hasEffectiveFilters = filters.some((f) => f.field && f.value.trim());
  const canRunRowsQuery = queryMode !== "rows" || hasEffectiveFilters;
  const countValue = Number(result?.count ?? 0);
  const allFilteredEntitiesSelected =
    filteredEntities.length > 0 &&
    filteredEntities.every((entity) => selectedEntityNames.includes(entity.name));

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
              查询历史 {history.length > 0 && <span className="badge badge-dim" style={{ marginLeft: 4 }}>{history.length}</span>}
            </button>
            <button className="btn btn-primary btn-sm" onClick={() => setShowImportPanel((v) => !v)}>
              从 Atlas 选择导入
            </button>
          </div>
        </div>
      </div>

      {showImportPanel && (
        <div style={{ padding: "0 28px 14px" }}>
          <div className="card fade-up">
            <div className="card-head">
              <div>
                <h3>Entity Governance · 实体治理导入</h3>
                <div style={{ color: "var(--t4)", fontSize: 12, marginTop: 4 }}>
                  从 Atlas 选择少量表生成 Lens 草稿；草稿不会暴露给 Agent，启用后才进入 MCP 查询面。
                </div>
              </div>
              <button className="btn btn-ghost btn-sm" onClick={() => setShowImportPanel(false)}>收起</button>
            </div>
            <div className="card-body">
              <div className="row gap-md mb-md wrap">
                <div style={{ width: 220 }}>
                  <div className="field-label mb-sm">数据库 Database</div>
                  <select className="input" value={importDatabase} onChange={(e) => void loadAtlasTables(e.target.value)}>
                    <option value="">选择数据库...</option>
                    {atlasDatabases.map((db) => (
                      <option key={db.database} value={db.database}>
                        {db.database} ({db.table_count})
                      </option>
                    ))}
                  </select>
                </div>
                <div style={{ flex: 1, minWidth: 260 }}>
                  <div className="field-label mb-sm">搜索表 Search Tables</div>
                  <input
                    className="input"
                    placeholder="输入表名、注释或引擎"
                    value={importTableQuery}
                    onChange={(e) => setImportTableQuery(e.target.value)}
                  />
                </div>
                <div style={{ alignSelf: "end" }} className="row gap-sm">
                  <span className="badge badge-dim">{selectedImportTables.length} selected</span>
                  <button
                    className="btn btn-primary btn-sm"
                    onClick={handleImportFromAtlas}
                    disabled={importing || !importDatabase || selectedImportTables.length === 0}
                    title="导入后先进入草稿，需要在 Lens 详情里启用后 Agent 才能发现"
                  >
                    {importing ? <><span className="spinner" /> 导入中</> : "导入为草稿"}
                  </button>
                </div>
              </div>

              <div style={{ maxHeight: 260, overflowY: "auto", border: "1px solid var(--border-0)", borderRadius: "var(--r)" }}>
                {loadingAtlasTables ? (
                  <div className="empty" style={{ padding: 20 }}><div className="empty-text">读取 Atlas 表列表...</div></div>
                ) : filteredAtlasTables.length > 0 ? (
                  <table className="dtable">
                    <thead>
                      <tr>
                        <th style={{ width: 48 }}></th>
                        <th>表 Table</th>
                        <th>注释 Comment</th>
                        <th>行数 Approx</th>
                        <th>列</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredAtlasTables.slice(0, 200).map((table) => (
                        <tr key={table.name}>
                          <td>
                            <input
                              type="checkbox"
                              checked={selectedImportTables.includes(table.name)}
                              onChange={() => toggleImportTable(table.name)}
                            />
                          </td>
                          <td className="mono">{table.name}</td>
                          <td style={{ color: table.comment ? "var(--teal)" : "var(--t4)" }}>{table.comment || "-"}</td>
                          <td className="mono">{table.row_count_approx?.toLocaleString?.() ?? table.row_count_approx}</td>
                          <td><span className="badge badge-dim">{table.column_count}</span></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : (
                  <div className="empty" style={{ padding: 20 }}>
                    <div className="empty-text">{importDatabase ? "没有匹配的表" : "先选择一个数据库"}</div>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      <div className="page-body" style={{ display: "flex", gap: 14, overflow: "hidden", padding: "14px 28px 28px" }}>
        {/* ── Entity list panel ── */}
        <div style={{ width: 320, flexShrink: 0, display: "flex", flexDirection: "column" }}>
          <div className="card fade-up" style={{ flex: 1, display: "flex", flexDirection: "column" }}>
            <div className="card-head">
              <h3>实体</h3>
              <span className="badge badge-teal">{filteredEntities.length}/{entities.length}</span>
            </div>
            <div className="card-body" style={{ borderBottom: "1px solid var(--border-0)" }}>
              <div className="row gap-sm">
                <input
                  className="input"
                  placeholder="搜索实体、表名或数据库"
                  value={entityQuery}
                  onChange={(e) => setEntityQuery(e.target.value)}
                />
                {entityDatabases.length > 1 && (
                  <select
                    className="input"
                    style={{ width: 120 }}
                    value={entityDatabase}
                    onChange={(e) => setEntityDatabase(e.target.value)}
                  >
                    <option value="">全部库</option>
                    {entityDatabases.map((db) => <option key={db} value={db}>{db}</option>)}
                  </select>
                )}
              </div>
              <div className="row gap-sm mt-sm wrap">
                <label className="row gap-xs" style={{ fontSize: 12, color: "var(--t3)" }} title="选择当前过滤结果，用于批量启用或转为草稿。">
                  <input
                    type="checkbox"
                    checked={allFilteredEntitiesSelected}
                    onChange={toggleCurrentEntities}
                  />
                  选择当前列表
                </label>
                <span className="badge badge-dim">{selectedEntityNames.length} selected</span>
                <button
                  className="btn btn-primary btn-sm"
                  onClick={() => void batchSetAgentVisibility(true)}
                  disabled={savingEntity || selectedEntityNames.length === 0}
                  title="批量启用后，Agent 可以通过 lens.list_entities 发现这些实体。"
                >
                  批量启用给 Agent
                </button>
                <button
                  className="btn btn-ghost btn-sm"
                  onClick={() => void batchSetAgentVisibility(false)}
                  disabled={savingEntity || selectedEntityNames.length === 0}
                  title="批量转为草稿后，Agent 将无法发现这些实体。"
                >
                  批量转为草稿
                </button>
              </div>
            </div>
            <div className="card-body flush" style={{ flex: 1, overflowY: "auto" }}>
              {filteredEntities.length > 0 ? (
                filteredEntities.map((e) => (
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
                    <div className="row gap-sm">
                      <input
                        type="checkbox"
                        checked={selectedEntityNames.includes(e.name)}
                        onClick={(event) => event.stopPropagation()}
                        onChange={() => toggleEntitySelection(e.name)}
                        title="选择此实体进行批量治理操作"
                      />
                      <div style={{ fontFamily: "var(--font-display)", fontWeight: 500, fontSize: 13 }}>
                        {e.display_name || e.name}
                      </div>
                    </div>
                    <div className="row gap-xs mt-xs" style={{ justifyContent: "space-between" }}>
                      <div className="row gap-xs">
                        <span className="badge badge-dim">{e.db_type}</span>
                        <span className="badge badge-dim">{e.field_count} 字段</span>
                        <span className="badge badge-dim">{e.database}</span>
                        <span className={e.enabled ? "badge badge-emerald" : "badge badge-coral"}>
                          {e.enabled ? "approved" : "draft"}
                        </span>
                      </div>
                      <div style={{ position: "relative" }}>
                        <button
                          className="btn btn-ghost btn-sm"
                          style={{ fontSize: 11, padding: "1px 7px", color: "var(--t3)" }}
                          onClick={(ev) => {
                            ev.stopPropagation();
                            setEntityMenu(entityMenu === e.name ? "" : e.name);
                          }}
                          title="更多操作"
                        >
                          ...
                        </button>
                        {entityMenu === e.name && (
                          <div
                            style={{
                              position: "absolute",
                              right: 0,
                              top: 24,
                              zIndex: 5,
                              minWidth: 96,
                              background: "var(--elevated)",
                              border: "1px solid var(--border-1)",
                              borderRadius: "var(--r)",
                              padding: 4,
                              boxShadow: "0 10px 24px rgba(0,0,0,0.28)",
                            }}
                            onClick={(ev) => ev.stopPropagation()}
                          >
                            <button
                              className="btn btn-danger btn-sm"
                              style={{ width: "100%", justifyContent: "center" }}
                              onClick={() => handleDeleteEntity(e.name)}
                            >
                              删除实体
                            </button>
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                ))
              ) : (
                <div className="empty" style={{ padding: 24 }}>
                  <div className="empty-text">
                    {error || (entities.length > 0 ? "没有匹配的实体" : `还没有实体。${atlasSummary || "Atlas 尚未加载 Schema。"} 可从 Atlas 导入生成查询实体。`)}
                  </div>
                  {entities.length === 0 && (
                    <div className="row gap-sm mt-md" style={{ justifyContent: "center" }}>
                      <button className="btn btn-primary btn-sm" onClick={() => setShowImportPanel(true)} disabled={importing}>
                        从 Atlas 选择导入
                      </button>
                    </div>
                  )}
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
                <h3>查询历史</h3>
                <button className="btn btn-danger btn-sm" onClick={clearHistory}>清空</button>
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
                        <span className="badge badge-dim">{entry.resultCount} 行</span>
                      )}
                      {entry.durationMs !== undefined && (
                        <span style={{ color: "var(--t4)", fontSize: 11 }}>{entry.durationMs}ms</span>
                      )}
                    </div>
                  ))
                ) : (
                  <div className="empty" style={{ padding: 16 }}>
                    <div className="empty-text">暂无查询历史</div>
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
                    <span className={selected.enabled ? "badge badge-emerald" : "badge badge-coral"}>
                      {selected.enabled ? "approved / Agent 可见" : "draft / Agent 不可见"}
                    </span>
                  </div>
                  <div className="row gap-sm">
                    <div className="entity-id-readonly" aria-label="实体 ID 来自 Atlas 数据库和表名，不允许修改">
                      <span className="entity-id-label">实体 ID</span>
                      <span className="mono entity-id-value">{selected.name}</span>
                      <span className="badge badge-dim">不可修改</span>
                    </div>
                    <button
                      className={selected.enabled ? "btn btn-ghost btn-sm" : "btn btn-primary btn-sm"}
                      onClick={() => void saveSelectedEntity({ enabled: !selected.enabled })}
                      disabled={savingEntity}
                      title={selected.enabled ? "停用后 Agent 将不再发现该实体" : "启用后 Agent 可以通过 Lens MCP 使用该实体"}
                    >
                      {selected.enabled ? "停用" : "启用给 Agent"}
                    </button>
                    <input
                      className="input"
                      style={{ width: 220 }}
                      placeholder="搜索字段、类型或语义"
                      value={fieldQuery}
                      onChange={(event) => setFieldQuery(event.target.value)}
                    />
                    <span style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--t4)", alignSelf: "center" }}>
                      {selected.database}.{selected.primary_table}
                    </span>
                  </div>
                </div>
                <div className="card-body flush" style={{ maxHeight: 200, overflowY: "auto" }}>
                  <table className="dtable">
                    <thead>
                      <tr>
                        <th>字段</th>
                        <th>类型</th>
                        <th>语义</th>
                        <th style={{ textAlign: "center" }} title="治理配置：是否允许这个字段出现在 filter 条件中。">可筛选</th>
                        <th style={{ textAlign: "center" }} title="治理配置：是否允许用这个字段排序。">可排序</th>
                        <th style={{ textAlign: "center" }} title="治理配置：敏感字段默认不返回，查询结果会尽量脱敏。">敏感</th>
                        <th title="默认安全字段影响 Preview 和未指定返回字段时的结果；本次查询字段只影响当前页面查询。">治理 / 本次查询</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredFieldNames.map((name) => {
                        const f = selected.fields[name];
                        return (
                        <tr key={f.name}>
                          <td className="mono">{f.name}</td>
                          <td><span className="badge badge-dim">{f.type || "string"}</span></td>
                          <td style={{ color: f.semantic ? "var(--teal)" : "var(--t4)", fontSize: 12 }}>
                            {f.semantic || "\u2014"}
                          </td>
                          <td style={{ textAlign: "center" }}>
                            <button className={`badge ${f.filterable ? "badge-teal" : "badge-dim"}`} style={{ border: "none", cursor: "pointer" }} title={f.filterable ? "点击后禁止该字段作为筛选条件" : "点击后允许该字段作为筛选条件"} onClick={() => patchField(f.name, { filterable: !f.filterable })}>
                              {f.filterable ? "是" : "否"}
                            </button>
                          </td>
                          <td style={{ textAlign: "center" }}>
                            <button className={`badge ${f.sortable ? "badge-teal" : "badge-dim"}`} style={{ border: "none", cursor: "pointer" }} title={f.sortable ? "点击后禁止该字段排序" : "点击后允许该字段排序"} onClick={() => patchField(f.name, { sortable: !f.sortable })}>
                              {f.sortable ? "是" : "否"}
                            </button>
                          </td>
                          <td style={{ textAlign: "center" }}>
                            <button className={`badge ${f.sensitive ? "badge-coral" : "badge-dim"}`} style={{ border: "none", cursor: "pointer" }} title={f.sensitive ? "点击后取消敏感标记" : "点击后标记为敏感，并从默认返回中移除"} onClick={() => patchField(f.name, { sensitive: !f.sensitive, default_visible: f.sensitive ? f.default_visible : false })}>
                              {f.sensitive ? "是" : "否"}
                            </button>
                          </td>
                          <td>
                            <div className="row gap-xs">
                              <button
                                className={`btn btn-ghost btn-sm`}
                                style={{ fontSize: 10, padding: "2px 6px" }}
                                onClick={() => patchField(f.name, { default_visible: !f.default_visible })}
                                title={f.default_visible ? "从默认安全返回字段中移除；Preview 和默认查询不会返回它" : "加入默认安全返回字段；Preview 和默认查询会返回它"}
                              >
                                {f.default_visible ? "移出默认字段" : "加入默认字段"}
                              </button>
                              {f.filterable && (
                                <button className="btn btn-ghost btn-sm" style={{ fontSize: 10, padding: "2px 6px" }} title="把这个字段加入下方筛选条件，需要填写筛选值后才能执行明细查询" onClick={() => addFieldFilter(f.name)}>
                                  加为筛选条件
                                </button>
                              )}
                              <button className="btn btn-ghost btn-sm" style={{ fontSize: 10, padding: "2px 6px" }} title="只影响本次查询返回字段，不修改 entity 治理配置" onClick={() => toggleField(f.name)}>
                                {selectedFields.includes(f.name) ? "本次不返回" : "本次返回"}
                              </button>
                            </div>
                          </td>
                        </tr>
                      );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Query builder */}
              <div className="card mb-md">
                <div className="card-head">
                  <h3>查询构建器</h3>
                  <div className="row gap-sm">
                    <button className="btn btn-ghost btn-sm" onClick={addFilter}>添加筛选</button>
                    <button
                      className="btn btn-primary btn-sm"
                      onClick={() => executeQuery()}
                      disabled={queryLoading || !canRunRowsQuery}
                      title={!canRunRowsQuery ? "明细查询需要筛选条件；如需看数据形态，请使用 Preview 样本。" : undefined}
                    >
                      {queryLoading ? <><span className="spinner" /> 查询中</> : "执行查询"}
                    </button>
                  </div>
                </div>
                <div className="card-body">
                  <div className="row gap-sm mb-md wrap">
                    <div className="field-label" style={{ alignSelf: "center" }}>常用模板</div>
                    <button className="btn btn-ghost btn-sm" onClick={runCountAll} disabled={queryLoading}>
                      统计总数 / 判断空表
                    </button>
                    <button className="btn btn-ghost btn-sm" onClick={applyIdFilterTemplate}>
                      按 ID 查询
                    </button>
                    <button className="btn btn-ghost btn-sm" onClick={applyDefaultFieldsTemplate}>
                      返回默认字段
                    </button>
                    <button className="btn btn-ghost btn-sm" onClick={runPreviewSample} disabled={queryLoading}>
                      预览样本 Preview
                    </button>
                  </div>
                  <div className="row gap-sm mb-md wrap">
                    <div className="field-label" style={{ alignSelf: "center" }}>查询模式</div>
                    <button
                      className={`btn btn-sm ${queryMode === "rows" ? "btn-primary" : "btn-ghost"}`}
                      onClick={() => setQueryMode("rows")}
                    >
                      明细
                    </button>
                    <button
                      className={`btn btn-sm ${queryMode === "count" ? "btn-primary" : "btn-ghost"}`}
                      onClick={() => setQueryMode("count")}
                    >
                      Count
                    </button>
                    <button
                      className={`btn btn-sm ${queryMode === "preview" ? "btn-primary" : "btn-ghost"}`}
                      onClick={() => {
                        setQueryMode("preview");
                        setSelectedFields([]);
                        setLimit((current) => Math.min(current, 20));
                      }}
                    >
                      Preview 样本
                    </button>
                    {queryMode === "rows" && !hasEffectiveFilters && (
                      <span className="badge badge-coral">明细查询需要筛选条件，避免扫表</span>
                    )}
                    {queryMode === "count" && (
                      <span className="badge badge-dim">统计当前实体行数；大表建议先加筛选条件</span>
                    )}
                    {queryMode === "preview" && (
                      <span className="badge badge-dim">只返回默认安全字段，最多 20 行，不代表全部数据</span>
                    )}
                  </div>

                  {/* Filters */}
                  {filters.length > 0 && (
                    <div className="mb-md">
                      <div className="field-label mb-sm">筛选条件</div>
                      {filters.map((f, i) => (
                        <div key={i} className="row gap-sm mb-sm">
                          <select className="input" style={{ width: 150 }} value={f.field} onChange={(e) => updateFilter(i, "field", e.target.value)}>
                            <option value="">选择字段...</option>
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
                            placeholder={f.op === "in" ? "值1, 值2, ..." : f.op === "between" ? "起始,结束" : "输入值..."}
                            value={f.value}
                            onChange={(e) => updateFilter(i, "value", e.target.value)}
                            onKeyDown={(e) => e.key === "Enter" && executeQuery()}
                          />
                          <button className="btn btn-ghost btn-sm" style={{ color: "var(--coral)", padding: "4px 8px" }} onClick={() => removeFilter(i)}>
                            移除
                          </button>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Fields */}
                  {queryMode === "rows" && (
                  <div className="mb-md">
                    <div className="field-label mb-sm">
                      返回字段 {selectedFields.length > 0 && `(${selectedFields.length})`}
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
                            title={isSensitive ? "敏感字段会被脱敏" : undefined}
                          >
                            {isSensitive ? "敏感 " : ""}{n}
                          </button>
                        );
                      })}
                    </div>
                    {selectedFields.length === 0 && (
                      <div style={{ fontSize: 11, color: "var(--t4)", marginTop: 4 }}>
                        未选择时返回默认可见字段
                      </div>
                    )}
                  </div>
                  )}

                  {/* Order & Limit */}
                  {queryMode !== "count" && (
                  <div className="row gap-md">
                    <div style={{ flex: 1 }}>
                      <div className="field-label mb-sm">{queryMode === "preview" ? "样本排序" : "排序"}</div>
                      <select className="input" value={orderBy} onChange={(e) => setOrderBy(e.target.value)}>
                        <option value="">默认排序</option>
                        {sortableFields.map((n) => (
                          <option key={n} value={n}>{n} ASC</option>
                        ))}
                        {sortableFields.map((n) => (
                          <option key={`${n}-desc`} value={`-${n}`}>{n} DESC</option>
                        ))}
                      </select>
                    </div>
                    <div style={{ width: 100 }}>
                      <div className="field-label mb-sm">返回上限</div>
                      <input
                        className="input"
                        type="number"
                        value={limit}
                        onChange={(e) => setLimit(Math.max(1, Math.min(queryMode === "preview" ? 20 : 100, Number(e.target.value))))}
                        min={1}
                        max={queryMode === "preview" ? 20 : 100}
                      />
                    </div>
                  </div>
                  )}
                </div>
              </div>

              {/* Results */}
              {result && (
                <div className="card fade-up">
                  <div className="card-head">
                    <h3>查询结果</h3>
                    <div className="row gap-sm">
                      {result.success ? (
                        <>
                          <span className="badge badge-emerald">
                            {queryMode === "count"
                              ? `Count ${result.count}`
                              : queryMode === "preview"
                                ? `Preview ${result.count} 行`
                                : `${result.count} 行`}
                          </span>
                          <span className="badge badge-dim">{result.duration_ms}ms</span>
                          {result.sql && (
                            <button
                              className="btn btn-ghost btn-sm"
                              onClick={() => setShowSql(!showSql)}
                            >
                              {showSql ? "隐藏 SQL" : "显示 SQL"}
                            </button>
                          )}
                        </>
                      ) : (
                        <span className="badge badge-coral">错误</span>
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
                    {result.success && queryMode === "count" ? (
                      <div className="stat" style={{ textAlign: "left", padding: "18px 20px" }}>
                        <div className="stat-val teal">{result.count?.toLocaleString()}</div>
                        <div className="stat-label">
                          {countValue === 0
                            ? hasEffectiveFilters ? "当前筛选条件没有命中数据" : "当前实体没有数据"
                            : hasEffectiveFilters ? "当前实体与筛选条件命中的行数" : "当前实体的行数"}
                        </div>
                      </div>
                    ) : result.success && result.data && result.data.length > 0 ? (
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
                        <div className="empty-text">没有返回结果</div>
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
                    {entityLoading ? "加载中..." : "选择一个实体后开始查询"}
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
