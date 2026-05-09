"""Atlas MCP 工具定义"""

import json

from mcp.server.fastmcp import FastMCP

from app.services.annotation_service import (
    batch_annotate as _batch_annotate,
    confirm_annotation as _confirm_annotation,
    get_annotation_stats as _get_annotation_stats,
    list_pending_annotations,
    save_annotation,
)
from app.services.schema_service import (
    collect_all,
    collect_schema,
    diff_schema,
    get_latest_snapshot,
    get_table_info,
    search_metadata,
)
from app.services.service_discovery import get_service_detail, get_services
from app.utils.audit import audited

mcp = FastMCP("atlas")


# ── 数据库元数据工具 ──────────────────────────


@mcp.tool()
@audited("get_schema")
async def get_schema(database: str = "", table: str = "") -> str:
    """获取数据库表结构信息，合并语义标注一起返回。

    - 不传 database：返回所有已采集数据库的概要
    - 传 database 不传 table：返回该库的所有表列表
    - 传 database 和 table：返回该表的完整字段信息（含语义）
    """
    if not database:
        # 返回已采集的数据库概要
        from app.services.schema_service import _snapshots

        summary = {}
        for db, snapshots in _snapshots.items():
            if snapshots:
                latest = snapshots[-1]
                summary[db] = {
                    "table_count": len(latest.table),
                    "snapshot_time": str(latest.created_at),
                }
        if not summary:
            return json.dumps(
                {"hint": "尚未采集任何 schema，请先调用 refresh 工具触发采集"},
                ensure_ascii=False,
            )
        return json.dumps(summary, ensure_ascii=False, default=str)

    if table:
        info = await get_table_info(database, table)
        if not info:
            return json.dumps(
                {"error": f"表 {database}.{table} 不存在或尚未采集"},
                ensure_ascii=False,
            )
        return json.dumps(info.model_dump(), ensure_ascii=False, default=str)

    # 返回库的表列表
    snapshot = await get_latest_snapshot(database)
    if not snapshot:
        return json.dumps(
            {"error": f"数据库 {database} 尚未采集，请先调用 refresh"},
            ensure_ascii=False,
        )
    tables = [
        {
            "name": t.name,
            "comment": t.comment,
            "column_count": len(t.column),
            "row_count_approx": t.row_count_approx,
        }
        for t in snapshot.table
    ]
    return json.dumps(tables, ensure_ascii=False, default=str)


@mcp.tool()
@audited("diff_schema")
async def diff_schema_tool(database: str) -> str:
    """对比当前 schema 与上次快照的差异。

    返回新增、删除、变更的表和字段。需要至少有两次采集快照才能 diff。
    """
    result = await diff_schema(database)
    if not result:
        return json.dumps(
            {"hint": "需要至少两次 schema 采集才能对比差异，请多调用几次 refresh"},
            ensure_ascii=False,
        )
    return json.dumps(result.model_dump(), ensure_ascii=False, default=str)


@mcp.tool()
@audited("search_meta")
async def search_meta(query: str) -> str:
    """全文搜索元数据。输入业务概念（如"退款""订单状态"），返回相关的表、字段。

    搜索范围包括：表名、字段名、MySQL 注释、语义标注。
    """
    result = await search_metadata(query)
    return json.dumps(result, ensure_ascii=False, default=str)


@mcp.tool()
@audited("annotate_column")
async def annotate_column(
    database: str,
    table: str,
    column: str,
    semantic: str,
    source: str = "ai",
) -> str:
    """为指定字段打语义标签。

    AI 调用时 source 默认为 "ai"，标注状态自动设为 pending（需人工确认）。
    人工调用时可设 source="manual"，自动确认。

    参数：
    - database: 数据库名
    - table: 表名
    - column: 字段名
    - semantic: 语义描述（如"订单金额"、"手机号-敏感"）
    - source: 标注来源 "ai" / "manual" / "auto"，默认 "ai"
    """
    aid = await save_annotation(database, table, column, semantic, source=source)
    if not aid:
        return json.dumps(
            {"error": "PG 不可用，标注未持久化"},
            ensure_ascii=False,
        )
    return json.dumps(
        {
            "id": aid,
            "database": database,
            "table": table,
            "column": column,
            "semantic": semantic,
            "source": source,
            "confirmed": source == "manual",
        },
        ensure_ascii=False,
    )


@mcp.tool()
@audited("batch_annotate")
async def batch_annotate(
    annotations: list[dict],
    source: str = "ai",
) -> str:
    """批量为多个字段打语义标签（AI 批量分析后一次性提交）。

    每条 annotation 需包含：database, table, column, semantic。
    source 默认 "ai"（pending 状态，需人工确认）。

    示例输入：
    annotations = [
        {"database": "test", "table": "order", "column": "amount", "semantic": "订单金额"},
        {"database": "test", "table": "order", "column": "phone", "semantic": "手机号-敏感字段"},
    ]
    """
    result = await _batch_annotate(annotations, source=source)
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
@audited("list_pending")
async def list_pending(database: str) -> str:
    """列出所有待确认的语义标注（AI 或自动推断生成、尚未经人工审查）。

    返回 confirmed=False 的所有标注，供人工逐条审查。
    """
    pending = await list_pending_annotations(database)
    return json.dumps(
        {"database": database, "count": len(pending), "annotations": pending},
        ensure_ascii=False,
        default=str,
    )


@mcp.tool()
@audited("confirm_annotation")
async def confirm_annotation(
    database: str,
    table: str,
    column: str,
    confirmed: bool = True,
) -> str:
    """确认或拒绝一条语义标注。

    - confirmed=True：标注生效，可被 Lens 消费
    - confirmed=False：标记为 rejected，不删除记录，可后续恢复确认

    参数：
    - database: 数据库名
    - table: 表名
    - column: 字段名
    - confirmed: True=确认 / False=标记驳回
    """
    ok = await _confirm_annotation(database, table, column, confirmed)
    action = "confirmed" if confirmed else "rejected"
    return json.dumps(
        {
            "database": database,
            "table": table,
            "column": column,
            "action": action,
            "success": ok,
        },
        ensure_ascii=False,
    )


@mcp.tool()
@audited("annotation_stats")
async def annotation_stats(database: str) -> str:
    """查看语义标注的整体覆盖情况。

    返回该数据库的标注统计：总数、已确认数、待确认数、各来源（auto/ai/manual）分布。
    用于评估标注进度和覆盖率。
    """
    stats = await _get_annotation_stats(database)
    if not stats:
        return json.dumps(
            {"error": "PG 不可用或无标注数据"},
            ensure_ascii=False,
        )
    stats["database"] = database
    return json.dumps(stats, ensure_ascii=False)


@mcp.tool()
@audited("refresh")
async def refresh(scope: str = "all") -> str:
    """手动触发元数据采集。

    scope:
    - "schema": 只采集数据库表结构
    - "service": 只采集服务列表
    - "all": 全部采集
    """
    results = {}

    if scope in ("schema", "all"):
        snapshots = await collect_all()
        results["schema"] = {
            s.database: f"采集到 {len(s.table)} 张表" for s in snapshots
        }

    if scope in ("service", "all"):
        services = await get_services()
        results["service"] = f"发现 {len(services)} 个服务"

    return json.dumps(results, ensure_ascii=False)


# ── 服务元数据工具 ──────────────────────────


@mcp.tool()
@audited("list_service")
async def list_service() -> str:
    """列出所有从 supervisor 采集到的业务服务。

    返回服务名称、运行状态、部署路径、日志路径等信息。
    """
    services = await get_services()
    return json.dumps(
        [s.model_dump() for s in services],
        ensure_ascii=False,
        default=str,
    )


@mcp.tool()
@audited("get_service")
async def get_service(name: str) -> str:
    """获取指定业务服务的详细信息。"""
    svc = await get_service_detail(name)
    if not svc:
        return json.dumps(
            {"error": f"未找到服务: {name}"},
            ensure_ascii=False,
        )
    return json.dumps(svc.model_dump(), ensure_ascii=False, default=str)
