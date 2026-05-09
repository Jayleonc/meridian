"""Entity 自动生成器 — 从 Atlas schema 自动创建 Lens 业务实体定义

核心逻辑：
1. 调用 Atlas REST API 获取数据库 schema（表+字段）
2. 为每张表自动生成 EntityDefinition:
   - field mapping: 列名 → EntityField
   - filterable: PK、索引列、短 varchar
   - sortable: 数字类型、日期类型
   - sensitive: 匹配敏感词列表（phone, id_card 等）
   - time_field: 自动检测时间字段（created_at, create_time 等）
   - default_visible: 非大字段，最多 12 个
3. 注册到 Lens entity_service
"""

import logging
import re

import httpx

from app.core.config import get_settings
from app.services.entity_service import (
    get_entity_definition,
    register_entity,
)

logger = logging.getLogger("lens.generator")

# ── 时间字段检测模式 ──
TIME_FIELD_PATTERNS = [
    "created_at", "create_time", "gmt_create", "gmt_created",
    "updated_at", "update_time", "gmt_modified", "modify_time",
    "created", "timestamp", "log_time", "event_time",
    "insert_time", "add_time",
]

# ── 数字类型（sortable） ──
NUMERIC_RE = re.compile(
    r"(int|bigint|smallint|tinyint|mediumint|decimal|numeric|float|double|real)",
    re.IGNORECASE,
)

# ── 日期类型（sortable + 可能是 time_field） ──
DATE_RE = re.compile(r"(datetime|timestamp|date)", re.IGNORECASE)

# ── 大字段（不 default_visible） ──
BLOB_RE = re.compile(r"(blob|text|longtext|mediumtext|json|binary|bytea)", re.IGNORECASE)

# ── 短字符串（filterable） ──
SHORT_VARCHAR_RE = re.compile(r"varchar\((\d+)\)", re.IGNORECASE)


def _detect_type(mysql_type: str) -> str:
    """将 MySQL/PG 物理类型映射为 Lens 语义类型"""
    t = mysql_type.lower()
    if DATE_RE.search(t):
        return "datetime"
    if NUMERIC_RE.search(t):
        if "decimal" in t or "numeric" in t or "float" in t or "double" in t:
            return "decimal"
        return "int"
    if "bool" in t:
        return "boolean"
    return "string"


def _is_sensitive(col_name: str) -> bool:
    """检查字段名是否匹配敏感词"""
    cfg = get_settings()
    name_lower = col_name.lower()
    for word in cfg.sensitive_fields:
        if word in name_lower:
            return True
    return False


def _detect_time_field(columns: list[dict]) -> str:
    """从字段列表中自动检测最佳时间字段"""
    for pattern in TIME_FIELD_PATTERNS:
        for col in columns:
            if col["name"].lower() == pattern:
                return col["name"]
    # 退而求其次：任何 datetime/timestamp 类型的字段
    for col in columns:
        if DATE_RE.search(col.get("type", "")):
            return col["name"]
    return ""


def _is_filterable(col: dict) -> bool:
    """判断字段是否适合做过滤条件"""
    if col.get("is_primary_key") or col.get("is_index"):
        return True
    # 短字符串（<= 64 字符）适合过滤
    m = SHORT_VARCHAR_RE.search(col.get("type", ""))
    if m and int(m.group(1)) <= 64:
        return True
    # 枚举类型
    if "enum" in col.get("type", "").lower():
        return True
    return False


def generate_entity_from_table(
    database: str,
    table_name: str,
    columns: list[dict],
    db_type: str = "mysql",
    datasource: str = "",
    row_count: int = 0,
    comment: str = "",
    enabled: bool = False,
) -> dict:
    """从单张表的 schema 生成 entity 定义（不注册，仅返回定义字典）"""
    fields: dict[str, dict] = {}
    visible_count = 0
    max_visible = 12

    for col in columns:
        name = col["name"]
        col_type = col.get("type", "")
        lens_type = _detect_type(col_type)
        is_blob = bool(BLOB_RE.search(col_type))
        sensitive = _is_sensitive(name)
        filterable = _is_filterable(col)
        sortable = bool(NUMERIC_RE.search(col_type) or DATE_RE.search(col_type))

        show = not is_blob and visible_count < max_visible and not sensitive
        if show:
            visible_count += 1

        fields[name] = {
            "name": name,
            "column": name,
            "type": lens_type,
            "semantic": col.get("semantic", "") or col.get("comment", ""),
            "filterable": filterable,
            "sortable": sortable,
            "sensitive": sensitive,
            "default_visible": show,
        }

    time_field = _detect_time_field(columns)

    return {
        "name": f"{database}__{table_name}",
        "display_name": comment or table_name,
        "database": database,
        "db_type": db_type,
        "datasource": datasource,
        "source_table": [table_name],
        "primary_table": table_name,
        "fields": fields,
        "constraint": {
            "time_field": time_field,
            "default_time_range_days": 7 if time_field else 0,
            "required_filter_fields": [],
        },
        "enabled": enabled,
    }


async def import_from_atlas(
    database: str | None = None,
    tables: list[str] | None = None,
    atlas_url: str = "http://127.0.0.1:3001",
    db_type: str = "mysql",
    datasource: str = "",
    overwrite: bool = False,
    enabled: bool = False,
) -> dict:
    """从 Atlas 导入 schema 并自动生成 entity 定义

    Args:
        database: 指定数据库名，留空则导入所有
        tables: 指定表名列表，留空则导入数据库下全部表
        atlas_url: Atlas 服务地址
        db_type: 数据库类型
        datasource: Lens 数据源名称
        overwrite: 是否覆盖已有的同名 entity
        enabled: 是否导入后立即启用；默认 false，先进入人工治理草稿

    Returns:
        { imported: int, skipped: int, errors: list[str], entities: list[str] }
    """
    result = {"imported": 0, "skipped": 0, "errors": [], "entities": []}
    selected_tables = set(tables or [])

    async with httpx.AsyncClient(timeout=10) as client:
        # 获取数据库列表
        if database:
            db_list = [database]
        else:
            try:
                resp = await client.get(f"{atlas_url}/api/schemas")
                resp.raise_for_status()
                data = resp.json()
                db_list = [d["database"] for d in data.get("databases", [])]
            except Exception as e:
                result["errors"].append(f"Failed to list databases from Atlas: {e}")
                return result

        for db in db_list:
            try:
                # 获取完整 schema
                resp = await client.get(f"{atlas_url}/api/schemas/{db}")
                resp.raise_for_status()
                snapshot = resp.json()

                if "error" in snapshot:
                    result["errors"].append(f"{db}: {snapshot['error']}")
                    continue

                schema_tables = snapshot.get("table", [])
                for table_data in schema_tables:
                    table_name = table_data["name"]
                    if selected_tables and table_name not in selected_tables:
                        continue
                    columns = table_data.get("column", [])

                    if not columns:
                        continue

                    entity_name = f"{db}__{table_name}"

                    # 检查是否已存在
                    existing = await get_entity_definition(entity_name)
                    if existing and not overwrite:
                        result["skipped"] += 1
                        continue

                    # 生成定义
                    defn = generate_entity_from_table(
                        database=db,
                        table_name=table_name,
                        columns=[c if isinstance(c, dict) else c.model_dump() for c in columns],
                        db_type=db_type,
                        datasource=datasource,
                        row_count=table_data.get("row_count_approx", 0),
                        comment=table_data.get("comment", ""),
                        enabled=enabled,
                    )

                    # 注册
                    await register_entity(
                        name=defn["name"],
                        display_name=defn["display_name"],
                        database=defn["database"],
                        db_type=defn["db_type"],
                        datasource=defn["datasource"],
                        source_table=defn["source_table"],
                        primary_table=defn["primary_table"],
                        fields=defn["fields"],
                        constraint=defn["constraint"],
                        enabled=defn["enabled"],
                    )

                    result["imported"] += 1
                    result["entities"].append(entity_name)
                    logger.info("Imported entity: %s (%d fields)", entity_name, len(defn["fields"]))

            except Exception as e:
                result["errors"].append(f"{db}: {e}")

    return result
