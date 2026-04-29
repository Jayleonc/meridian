/** Meridian API Client */

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!resp.ok) {
    let detail = `${resp.status} ${resp.statusText}`;
    try {
      const body = await resp.json();
      if (typeof body?.detail === "string") detail = body.detail;
      else if (typeof body?.error === "string") detail = body.error;
    } catch {
      // Keep the HTTP status fallback.
    }
    throw new Error(detail);
  }
  return resp.json() as Promise<T>;
}

// ── Atlas ──

export interface ServiceInfo {
  name: string;
  status: string;
  pid: number;
  deploy_path: string;
  log_path: string;
  databases: string[];
}

export interface AtlasStatus {
  connections: { mysql: string; postgresql: string };
  databases: Record<string, { table_count: number; snapshot_time: string; snapshot_count: number }>;
  total_databases: number;
}

// Schema types
export interface ColumnInfo {
  name: string;
  type: string;
  nullable: boolean;
  comment: string;
  semantic: string;
  semantic_source: string;
  is_primary_key: boolean;
  is_index: boolean;
}

export interface TableInfo {
  database: string;
  name: string;
  comment: string;
  column: ColumnInfo[];
  row_count_approx: number;
  engine: string;
  create_time: string;
}

export interface SchemaSnapshot {
  id: string;
  database: string;
  table: TableInfo[];
  created_at: string;
}

export interface TableSummary {
  name: string;
  comment: string;
  column_count: number;
  row_count_approx: number;
  engine: string;
}

export interface SchemaDiff {
  database: string;
  added_table: string[];
  removed_table: string[];
  modified_table: Array<{
    table: string;
    added_column: Array<{ name: string; change: string }>;
    removed_column: Array<{ name: string; change: string }>;
    modified_column: Array<{ name: string; change: string; change_detail: string[] }>;
  }>;
}

export interface Annotation {
  database: string;
  table: string;
  column: string;
  semantic: string;
  source: string;
  confirmed: boolean;
}

export const atlas = {
  health: () => request<{ status: string }>("/svc/atlas/health"),
  status: () => request<AtlasStatus>("/svc/atlas/status"),

  // Services
  listServices: () =>
    request<{ count: number; service: ServiceInfo[] }>("/api/atlas/services"),
  refreshServices: () =>
    request<{ count: number; service: ServiceInfo[] }>("/api/atlas/services/refresh", {
      method: "POST",
    }),
  getService: (name: string) => request<ServiceInfo>(`/api/atlas/services/${name}`),

  // Schemas
  listDatabases: () =>
    request<{ databases: Array<{ database: string; table_count: number; snapshot_count: number; last_collected: string }> }>(
      "/api/atlas/schemas"
    ),
  getSchema: (database: string) => request<SchemaSnapshot>(`/api/atlas/schemas/${database}`),
  listTables: (database: string) =>
    request<{ database: string; count: number; tables: TableSummary[] }>(
      `/api/atlas/schemas/${database}/tables`
    ),
  getTable: (database: string, table: string) =>
    request<TableInfo>(`/api/atlas/schemas/${database}/tables/${table}`),
  diffSchema: (database: string) =>
    request<SchemaDiff | { message: string }>(`/api/atlas/schemas/${database}/diff`),
  collectSchema: (database?: string) =>
    request<{ collected: number }>("/api/atlas/schemas/collect" + (database ? `?database=${database}` : ""), {
      method: "POST",
    }),
  searchMeta: (q: string) =>
    request<{ query: string; matched_table: TableInfo[]; matched_column: Array<Record<string, string>>; matched_service: ServiceInfo[] }>(
      `/api/atlas/schemas/search/meta?q=${encodeURIComponent(q)}`
    ),

  // Annotations
  listAnnotations: (database: string, table?: string) =>
    request<{ count: number; annotations: Annotation[] }>(
      `/api/atlas/annotations/${database}` + (table ? `?table=${table}` : "")
    ),
  pendingAnnotations: (database: string) =>
    request<{ count: number; annotations: Annotation[] }>(
      `/api/atlas/annotations/${database}/pending`
    ),
  annotationStats: (database: string) =>
    request<Record<string, unknown>>(`/api/atlas/annotations/${database}/stats`),
  annotate: (data: { database: string; table: string; column: string; semantic: string; source?: string }) =>
    request<{ id: string; status: string }>("/api/atlas/annotations/annotate", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  confirmAnnotation: (data: { database: string; table: string; column: string; confirmed: boolean }) =>
    request<{ confirmed: boolean; success: boolean }>("/api/atlas/annotations/confirm", {
      method: "POST",
      body: JSON.stringify(data),
    }),
};

// ── Probe ──

export interface LogItem {
  timestamp: string;
  level: string;
  service?: string;
  request_id?: string | null;
  source: string;
  text: string;
  file: string;
  line_number: number;
}

export interface SearchResult {
  query: Record<string, unknown>;
  summary: {
    total_matches: number;
    returned: number;
    limit?: number;
    truncated: boolean;
    time_range?: { start: string; end: string };
  };
  items: LogItem[];
  next_actions?: string[];
}

export interface LogContext {
  file: string;
  line_number: number;
  context: {
    before: string[];
    match: string;
    after: string[];
  };
}

export interface TraceEntry {
  timestamp: string;
  level: string;
  service: string;
  source: string;
  message: string;
  request_id?: string;
}

export interface TraceSummary {
  request_id: string;
  total_lines: number;
  time_range: string;
  searched_hours: number;
  services: string[];
  error_count: number;
  warn_count: number;
  errors: TraceEntry[];
  warns: TraceEntry[];
  timeline: TraceEntry[];
  hint: string;
  next_actions?: string[];
}

export const probe = {
  health: () => request<{ status: string }>("/svc/probe/health"),
  listServices: () =>
    request<{ services: string[]; source: string }>("/api/probe/logs/services"),
  tailErrors: (hoursBack = 1, limit = 50, includeFull = false) =>
    request<SearchResult>(
      `/api/probe/logs/errors?hours_back=${hoursBack}&limit=${limit}&include_full=${includeFull ? "true" : "false"}`
    ),
  search: (body: {
    keyword: string;
    start_time?: string;
    end_time?: string;
    level?: string;
    limit?: number;
    include_full?: boolean;
    service?: string;
  }) =>
    request<SearchResult>("/api/probe/logs/search", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  trace: (requestId: string, backHours = 0, hintTime?: string) => {
    let url = `/api/probe/logs/trace/${encodeURIComponent(requestId)}?back_hours=${backHours}`;
    if (hintTime) url += `&hint_time=${encodeURIComponent(hintTime)}`;
    return request<TraceSummary>(url);
  },
  context: (file: string, lineNumber: number, before = 20, after = 20) =>
    request<LogContext>(
      `/api/probe/logs/context?file=${encodeURIComponent(file)}&line_number=${lineNumber}&before=${before}&after=${after}`
    ),
  tailService: (
    service: string,
    opts?: { hoursBack?: number; level?: string; keyword?: string; limit?: number; includeFull?: boolean; excludeNoise?: boolean }
  ) => {
    const q = new URLSearchParams({
      hours_back: String(opts?.hoursBack ?? 1),
      limit: String(opts?.limit ?? 200),
      include_full: opts?.includeFull ? "true" : "false",
    });
    if (opts?.level) q.set("level", opts.level);
    if (opts?.keyword) q.set("keyword", opts.keyword);
    if (opts?.excludeNoise) q.set("exclude_noise", "true");
    return request<SearchResult>(`/api/probe/logs/services/${encodeURIComponent(service)}/tail?${q.toString()}`);
  },
};

// ── Lens ──

export interface EntitySummary {
  name: string;
  display_name: string;
  database: string;
  db_type: string;
  field_count: number;
  enabled: boolean;
}

export interface EntityField {
  name: string;
  column: string;
  type: string;
  semantic: string;
  filterable: boolean;
  sortable: boolean;
  sensitive: boolean;
  default_visible: boolean;
}

export interface EntityDetail {
  id: string;
  name: string;
  display_name: string;
  database: string;
  db_type: string;
  datasource: string;
  source_table: string[];
  primary_table: string;
  join_clause: string;
  fields: Record<string, EntityField>;
  constraint: {
    time_field: string;
    default_time_range_days: number;
    required_filter_fields: string[];
  };
  enabled: boolean;
}

export interface QueryResult {
  success: boolean;
  data?: Record<string, unknown>[];
  count?: number;
  sql?: string;
  duration_ms?: number;
  error?: string;
}

export interface FilterCondition {
  field: string;
  op: string;
  value: unknown;
}

export interface QueryDSL {
  entity: string;
  filter?: FilterCondition[];
  field?: string[];
  order_by?: string;
  limit?: number;
  time_range?: { start: string; end: string };
}

export const lens = {
  health: () => request<{ status: string }>("/svc/lens/health"),
  status: () =>
    request<{
      connections: { mysql: string; postgresql: string };
      entities: {
        cached_count: number;
        entities: Array<{ name: string; display_name: string; enabled: boolean }>;
      };
    }>("/svc/lens/status"),
  listEntities: () =>
    request<{ count: number; entity: EntitySummary[] }>("/api/lens/entities"),
  describeEntity: (name: string) => request<EntityDetail>(`/api/lens/entities/${name}`),
  query: (dsl: QueryDSL) =>
    request<QueryResult>("/api/lens/entities/query", {
      method: "POST",
      body: JSON.stringify(dsl),
    }),
  validate: (dsl: QueryDSL) =>
    request<{ valid: boolean; errors: string[]; warnings: string[] }>(
      "/api/lens/entities/validate",
      { method: "POST", body: JSON.stringify(dsl) }
    ),
  importFromAtlas: (opts?: { database?: string; overwrite?: boolean }) =>
    request<{ imported: number; skipped: number; errors: string[]; entities: string[] }>(
      "/api/lens/entities/import-from-atlas",
      {
        method: "POST",
        body: JSON.stringify({
          database: opts?.database || "",
          overwrite: opts?.overwrite || false,
        }),
      }
    ),
  deleteEntity: (name: string) =>
    request<{ deleted: boolean; name: string }>(`/api/lens/entities/${name}`, {
      method: "DELETE",
    }),
};

// ── Agent Chat ──

export interface ChatConfig {
  provider: string;
  model: string;
  configured: boolean;
  base_url?: string | null;
  max_tool_rounds: number;
  tools: string[];
}

export interface ChatToolCall {
  id: string;
  name: string;
  arguments: Record<string, unknown>;
  result: unknown;
  error?: string | null;
  duration_ms: number;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  created_at: number;
  tool_calls: ChatToolCall[];
}

export interface ChatSession {
  id: string;
  title: string;
  created_at: number;
  updated_at: number;
  messages: ChatMessage[];
}

export interface ChatSessionSummary {
  id: string;
  title: string;
  created_at: number;
  updated_at: number;
  message_count: number;
  last_message_role?: string | null;
  last_message_preview: string;
}

export interface ChatSessionListResponse {
  sessions: ChatSessionSummary[];
}

export interface ChatTurnResponse {
  session_id: string;
  provider: string;
  model: string;
  assistant: ChatMessage;
  tool_calls: ChatToolCall[];
  session: ChatSession;
}

export const chat = {
  config: () => request<ChatConfig>("/api/chat/config"),
  createSession: (title = "排障会话") =>
    request<ChatSession>("/api/chat/sessions", {
      method: "POST",
      body: JSON.stringify({ title }),
    }),
  listSessions: (limit = 30) =>
    request<ChatSessionListResponse>(`/api/chat/sessions?limit=${limit}`),
  getSession: (sessionId: string) =>
    request<ChatSession>(`/api/chat/sessions/${sessionId}`),
  sessionEventsUrl: (sessionId: string, after: number, timeoutSeconds = 120) =>
    `/api/chat/sessions/${encodeURIComponent(sessionId)}/events?after=${after}&timeout_seconds=${timeoutSeconds}`,
  sendMessage: (sessionId: string, content: string) =>
    request<ChatTurnResponse>(`/api/chat/sessions/${sessionId}/messages`, {
      method: "POST",
      body: JSON.stringify({ content }),
    }),
};

// ── Utility ──

export type ServiceStatus = "online" | "offline" | "checking";

export async function checkServiceHealth(
  name: "atlas" | "probe" | "lens"
): Promise<ServiceStatus> {
  try {
    const fn = { atlas: atlas.health, probe: probe.health, lens: lens.health }[name];
    const result = await fn();
    return result.status === "ok" ? "online" : "offline";
  } catch {
    return "offline";
  }
}
