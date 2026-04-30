"""Explicit local demo adapter for Lens.

The adapter is intentionally named ``demo-memory`` and is only used by entity
definitions that opt into that datasource. Production entities continue to use
the configured MySQL/PostgreSQL adapters.
"""

from __future__ import annotations

from typing import Any

from app.schemas.query import EntityDefinition, QueryDSL
from app.services.entity_service import register_entity

DEMO_DATASOURCE = "demo-memory"
DEMO_DATABASE = "meridian_demo"

DEMO_ROWS: dict[tuple[str, str], list[dict[str, Any]]] = {
    (DEMO_DATABASE, "orders"): [
        {
            "order_id": "ORD-1001",
            "user_id": "U-001",
            "status": "paid",
            "amount": 299.0,
            "pay_status": "success",
            "callback_status": "delayed",
            "created_at": "2026-04-29 10:02:11",
            "updated_at": "2026-04-29 10:03:48",
        },
        {
            "order_id": "ORD-1002",
            "user_id": "U-002",
            "status": "pending",
            "amount": 88.0,
            "pay_status": "processing",
            "callback_status": "waiting",
            "created_at": "2026-04-29 10:11:03",
            "updated_at": "2026-04-29 10:11:03",
        },
        {
            "order_id": "ORD-1003",
            "user_id": "U-003",
            "status": "closed",
            "amount": 128.5,
            "pay_status": "failed",
            "callback_status": "not_required",
            "created_at": "2026-04-29 11:20:00",
            "updated_at": "2026-04-29 11:21:10",
        },
        {
            "order_id": "ORD-1004",
            "user_id": "U-001",
            "status": "paid",
            "amount": 560.0,
            "pay_status": "success",
            "callback_status": "success",
            "created_at": "2026-04-30 09:14:22",
            "updated_at": "2026-04-30 09:15:01",
        },
    ],
    (DEMO_DATABASE, "payment_callback"): [
        {
            "callback_id": "CB-9001",
            "order_id": "ORD-1001",
            "channel": "wechat",
            "status": "retrying",
            "retry_count": 2,
            "last_error": "downstream timeout",
            "received_at": "2026-04-29 10:02:31",
            "processed_at": "",
        },
        {
            "callback_id": "CB-9002",
            "order_id": "ORD-1004",
            "channel": "alipay",
            "status": "success",
            "retry_count": 0,
            "last_error": "",
            "received_at": "2026-04-30 09:14:36",
            "processed_at": "2026-04-30 09:14:39",
        },
    ],
    (DEMO_DATABASE, "users"): [
        {
            "user_id": "U-001",
            "phone": "13800000001",
            "tier": "gold",
            "status": "active",
            "created_at": "2025-12-01 12:00:00",
        },
        {
            "user_id": "U-002",
            "phone": "13800000002",
            "tier": "standard",
            "status": "active",
            "created_at": "2026-01-08 09:10:00",
        },
        {
            "user_id": "U-003",
            "phone": "13800000003",
            "tier": "standard",
            "status": "locked",
            "created_at": "2026-02-14 18:30:00",
        },
    ],
}


class DemoMemoryAdapter:
    @property
    def name(self) -> str:
        return DEMO_DATASOURCE

    @property
    def db_type(self) -> str:
        return "demo"

    async def init_pool(self) -> None:
        return None

    async def close_pool(self) -> None:
        return None

    async def execute_readonly_query(
        self,
        sql: str,
        params: tuple | None = None,
        timeout: int = 30,
    ) -> list[dict]:
        return []

    async def get_table_row_count(self, database: str, table: str) -> int:
        return len(DEMO_ROWS.get((database, table), []))

    async def execute_dsl_query(self, dsl: QueryDSL, entity: EntityDefinition) -> list[dict]:
        rows = list(DEMO_ROWS.get((entity.database, entity.primary_table), []))

        for condition in dsl.filter:
            rows = [row for row in rows if _match(row.get(condition.field), condition.op, condition.value)]

        if dsl.order_by:
            field = dsl.order_by.lstrip("-")
            reverse = dsl.order_by.startswith("-")
            rows.sort(key=lambda row: row.get(field) or "", reverse=reverse)

        rows = rows[: dsl.limit]

        selected_fields = dsl.field or [
            name for name, field in entity.fields.items() if field.default_visible
        ]
        if not selected_fields:
            selected_fields = list(entity.fields)

        result = []
        for row in rows:
            item = {}
            for field_name in selected_fields:
                field = entity.fields.get(field_name)
                if not field:
                    continue
                value = row.get(field.column or field_name)
                item[field_name] = _mask(value) if field.sensitive else value
            result.append(item)
        return result


def _match(value: Any, op: str, expected: Any) -> bool:
    if op == "in":
        values = expected if isinstance(expected, list) else [expected]
        return any(_match(value, "eq", item) for item in values)
    if op == "between":
        if not isinstance(expected, list) or len(expected) != 2:
            return False
        return _compare(value, expected[0]) >= 0 and _compare(value, expected[1]) <= 0
    if op == "like":
        needle = str(expected).strip("%").lower()
        return needle in str(value or "").lower()

    cmp = _compare(value, expected)
    if op == "eq":
        return cmp == 0
    if op == "ne":
        return cmp != 0
    if op == "gt":
        return cmp > 0
    if op == "gte":
        return cmp >= 0
    if op == "lt":
        return cmp < 0
    if op == "lte":
        return cmp <= 0
    return False


def _compare(left: Any, right: Any) -> int:
    left_value = _coerce(left)
    right_value = _coerce(right)
    if left_value == right_value:
        return 0
    return 1 if left_value > right_value else -1


def _coerce(value: Any) -> Any:
    if isinstance(value, int | float):
        return value
    text = str(value or "")
    try:
        if "." in text:
            return float(text)
        return int(text)
    except ValueError:
        return text


def _mask(value: Any) -> str:
    text = str(value or "")
    if len(text) <= 4:
        return "****" if text else ""
    return f"{text[:3]}****{text[-2:]}"


def demo_entity_definitions() -> list[dict[str, Any]]:
    common = {
        "database": DEMO_DATABASE,
        "db_type": "demo",
        "datasource": DEMO_DATASOURCE,
        "enabled": True,
    }
    return [
        {
            **common,
            "name": "demo_order",
            "display_name": "Demo 订单",
            "source_table": ["orders"],
            "primary_table": "orders",
            "fields": {
                "order_id": _field("order_id", "订单号"),
                "user_id": _field("user_id", "用户 ID"),
                "status": _field("status", "订单状态"),
                "amount": _field("amount", "订单金额", type_="decimal"),
                "pay_status": _field("pay_status", "支付状态"),
                "callback_status": _field("callback_status", "回调处理状态"),
                "created_at": _field("created_at", "创建时间", type_="datetime"),
                "updated_at": _field("updated_at", "更新时间", type_="datetime"),
            },
            "constraint": {"time_field": "", "default_time_range_days": 0, "required_filter_fields": []},
        },
        {
            **common,
            "name": "demo_payment_callback",
            "display_name": "Demo 支付回调",
            "source_table": ["payment_callback"],
            "primary_table": "payment_callback",
            "fields": {
                "callback_id": _field("callback_id", "回调 ID"),
                "order_id": _field("order_id", "订单号"),
                "channel": _field("channel", "支付渠道"),
                "status": _field("status", "回调状态"),
                "retry_count": _field("retry_count", "重试次数", type_="int"),
                "last_error": _field("last_error", "最近错误", default_visible=True, filterable=False),
                "received_at": _field("received_at", "收到时间", type_="datetime"),
                "processed_at": _field("processed_at", "处理完成时间", type_="datetime"),
            },
            "constraint": {"time_field": "", "default_time_range_days": 0, "required_filter_fields": []},
        },
        {
            **common,
            "name": "demo_user",
            "display_name": "Demo 用户",
            "source_table": ["users"],
            "primary_table": "users",
            "fields": {
                "user_id": _field("user_id", "用户 ID"),
                "phone": _field("phone", "手机号", sensitive=True),
                "tier": _field("tier", "用户等级"),
                "status": _field("status", "账户状态"),
                "created_at": _field("created_at", "注册时间", type_="datetime"),
            },
            "constraint": {"time_field": "", "default_time_range_days": 0, "required_filter_fields": []},
        },
    ]


def _field(
    name: str,
    semantic: str,
    *,
    type_: str = "string",
    filterable: bool = True,
    sortable: bool = True,
    sensitive: bool = False,
    default_visible: bool = True,
) -> dict[str, Any]:
    return {
        "name": name,
        "column": name,
        "type": type_,
        "semantic": semantic,
        "filterable": filterable,
        "sortable": sortable,
        "sensitive": sensitive,
        "default_visible": default_visible,
    }


async def seed_demo_entities() -> dict:
    imported = []
    for definition in demo_entity_definitions():
        entity = await register_entity(**definition)
        imported.append(entity.name)
    return {
        "imported": len(imported),
        "skipped": 0,
        "errors": [],
        "entities": imported,
        "datasource": DEMO_DATASOURCE,
    }
