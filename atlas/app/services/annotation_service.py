"""语义标注服务 — CRUD + 合并逻辑

三层语义模型的持久化管理层：
  auto   — 自动推断（schema_service 采集时写入）
  rule   — 规则增强（semantic.py 规则匹配）
  manual — 人工标注（Console API 写入）

合并策略：manual > rule > auto
"""

import logging

from app.adapters import pg_adapter

logger = logging.getLogger("atlas.annotation")


async def save_annotation(
    database: str,
    table: str,
    column: str,
    semantic: str,
    source: str = "manual",
    confirmed: bool | None = None,
) -> str:
    """保存语义标注（UPSERT）。

    - source='manual' 时默认 confirmed=True
    - source='auto' 时默认 confirmed=False
    返回标注 id（PG 不可用时返回空串）。
    """
    if confirmed is None:
        confirmed = source == "manual"

    aid = await pg_adapter.save_annotation(
        database_name=database,
        table_name=table,
        column_name=column,
        semantic=semantic,
        source=source,
        confirmed=confirmed,
    )
    if aid:
        logger.debug("标注已保存: %s.%s.%s (%s)", database, table, column, source)
    return aid


async def get_annotation(database: str, table: str, column: str) -> dict | None:
    """获取单条标注。"""
    return await pg_adapter.get_annotation(database, table, column)


async def get_annotations(database: str, table: str | None = None) -> list[dict]:
    """获取某个库（可选某张表）的所有标注。"""
    return await pg_adapter.get_annotations(database, table)


async def delete_annotation(database: str, table: str, column: str) -> bool:
    """删除单条标注。"""
    return await pg_adapter.delete_annotation(database, table, column)


async def list_pending_annotations(database: str) -> list[dict]:
    """列出所有 confirmed=False 的标注（待人工确认，含 auto/ai 来源）。"""
    return await pg_adapter.list_pending_annotations(database)


async def get_merged_semantics(database: str, table: str) -> dict[str, dict]:
    """获取合并后的语义标注。

    返回 {column_name: {semantic, source, confirmed}} 字典。
    如果同一个字段既有 auto 又有 manual 标注，manual 的会覆盖 auto
    （因为 PG 里 UNIQUE 约束保证同一个 (database, table, column) 只有一条，
     save_annotation 的 UPSERT 会用最后一次写入覆盖）。

    该函数的核心价值是：给 schema_service 提供一个"该表字段应该用什么语义"的合并视图，
    让手动标注优先于自动推断。
    """
    annotations = await pg_adapter.get_annotations(database, table)
    result: dict[str, dict] = {}
    for ann in annotations:
        col = ann["column_name"]
        # 如果已有记录，只在新记录优先级更高时覆盖
        if col in result:
            existing_priority = _source_priority(result[col]["source"])
            new_priority = _source_priority(ann["source"])
            if new_priority <= existing_priority:
                continue
        result[col] = {
            "semantic": ann["semantic"],
            "source": ann["source"],
            "confirmed": ann["confirmed"],
        }
    return result


async def batch_annotate(
    annotations: list[dict],
    source: str = "ai",
) -> dict:
    """批量打标签。每条 annotation 需含 database, table, column, semantic。

    返回 {success: int, failed: int, details: [...]}。
    """
    if source == "ai":
        confirmed = False
    elif source == "manual":
        confirmed = True
    else:
        confirmed = False

    success = 0
    failed = 0
    details = []
    for ann in annotations:
        try:
            aid = await pg_adapter.save_annotation(
                database_name=ann["database"],
                table_name=ann["table"],
                column_name=ann["column"],
                semantic=ann["semantic"],
                source=source,
                confirmed=confirmed,
            )
            if aid:
                success += 1
                details.append({"column": f"{ann['table']}.{ann['column']}", "status": "ok"})
            else:
                failed += 1
                details.append({
                    "column": f"{ann['table']}.{ann['column']}",
                    "status": "skipped",
                    "reason": "PG 不可用",
                })
        except Exception as e:
            failed += 1
            details.append({
                "column": f"{ann['table']}.{ann['column']}",
                "status": "error",
                "reason": str(e),
            })
            logger.warning("批量标注失败: %s — %s", ann, e)
    return {"success": success, "failed": failed, "details": details}


async def confirm_annotation(
    database: str, table: str, column: str, confirmed: bool = True
) -> bool:
    """确认或拒绝标注。confirmed=False 时删除该标注。"""
    return await pg_adapter.confirm_annotation(database, table, column, confirmed)


async def get_annotation_stats(database: str) -> dict:
    """获取标注统计。"""
    return await pg_adapter.get_annotation_stats(database)


def _source_priority(source: str) -> int:
    """标注来源优先级：manual > rule > ai > auto。"""
    return {"manual": 4, "rule": 3, "ai": 2, "auto": 1}.get(source, 0)
