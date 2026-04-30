"""Atlas 数据模型"""

from datetime import datetime

from pydantic import BaseModel


# ── 数据库元数据 ──────────────────────────────


class ColumnInfo(BaseModel):
    """字段信息（来自 information_schema + 语义标注）"""

    name: str
    type: str  # varchar(32), bigint, etc.
    nullable: bool = True
    comment: str = ""  # MySQL COLUMN_COMMENT
    semantic: str = ""  # 语义描述（自动推断或人工标注）
    semantic_source: str = "auto"  # auto / rule / manual
    is_primary_key: bool = False
    is_index: bool = False


class TableInfo(BaseModel):
    """表信息"""

    database: str
    name: str
    comment: str = ""  # MySQL TABLE_COMMENT
    column: list[ColumnInfo] = []
    row_count_approx: int = 0
    engine: str = ""
    create_time: str = ""


class SchemaSnapshot(BaseModel):
    """一次完整的 schema 采集快照"""

    id: str = ""
    database: str
    table: list[TableInfo] = []
    created_at: datetime | None = None


# ── Schema Diff ──────────────────────────────


class ColumnDiff(BaseModel):
    name: str
    old_type: str | None = None
    new_type: str | None = None
    old_comment: str | None = None
    new_comment: str | None = None
    old_nullable: bool | None = None
    new_nullable: bool | None = None
    change: str = ""  # added / removed / modified
    change_detail: list[str] = []  # 描述具体变更内容，如 ["type", "comment", "nullable"]


class TableDiff(BaseModel):
    table: str
    added_column: list[ColumnDiff] = []
    removed_column: list[ColumnDiff] = []
    modified_column: list[ColumnDiff] = []


class SchemaDiff(BaseModel):
    """两次快照的差异"""

    database: str
    added_table: list[str] = []
    removed_table: list[str] = []
    modified_table: list[TableDiff] = []
    snapshot_time: datetime | None = None
    previous_time: datetime | None = None


# ── 服务元数据 ──────────────────────────────


class ServiceInfo(BaseModel):
    """业务服务信息"""

    name: str
    status: str = "UNKNOWN"  # RUNNING / STOPPED / FATAL / UNKNOWN
    source: str = ""  # supervisor / static / probe_logs
    pid: int | None = None
    deploy_path: str = ""
    log_path: str = ""
    uptime: str = ""
    database_list: list[str] = []  # 关联的数据库


# ── 语义标注 ──────────────────────────────


class SemanticAnnotation(BaseModel):
    """语义标注条目"""

    database: str
    table: str
    column: str = ""  # 空则为表级标注
    semantic: str
    source: str = "manual"  # auto / rule / manual
    confirmed: bool = False


# ── 搜索结果 ──────────────────────────────


class MetadataSearchResult(BaseModel):
    """元数据搜索结果"""

    query: str
    matched_table: list[TableInfo] = []
    matched_column: list[dict] = []  # {database, table, column, semantic}
    matched_service: list[ServiceInfo] = []
