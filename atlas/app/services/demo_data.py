"""Local demo data for Atlas.

This is only used when a developer explicitly asks Atlas to bootstrap a
small local demonstration dataset. It keeps the normal MySQL/PG collection
path untouched.
"""

from datetime import datetime

from app.schemas.metadata import ColumnInfo, SchemaSnapshot, ServiceInfo, TableInfo

DEMO_DATABASE = "meridian_demo"


def _column(
    name: str,
    type_: str,
    *,
    comment: str = "",
    semantic: str = "",
    primary: bool = False,
    index: bool = False,
    nullable: bool = True,
) -> ColumnInfo:
    return ColumnInfo(
        name=name,
        type=type_,
        nullable=nullable,
        comment=comment,
        semantic=semantic or comment,
        semantic_source="demo",
        is_primary_key=primary,
        is_index=index or primary,
    )


def build_demo_snapshot() -> SchemaSnapshot:
    return SchemaSnapshot(
        database=DEMO_DATABASE,
        created_at=datetime.now(),
        table=[
            TableInfo(
                database=DEMO_DATABASE,
                name="orders",
                comment="订单主表",
                engine="demo",
                row_count_approx=4,
                column=[
                    _column("order_id", "varchar(32)", comment="订单号", primary=True, nullable=False),
                    _column("user_id", "varchar(32)", comment="用户 ID", index=True, nullable=False),
                    _column("status", "varchar(24)", comment="订单状态", index=True, nullable=False),
                    _column("amount", "decimal(10,2)", comment="订单金额", nullable=False),
                    _column("pay_status", "varchar(24)", comment="支付状态", index=True, nullable=False),
                    _column("callback_status", "varchar(24)", comment="回调处理状态", index=True, nullable=False),
                    _column("created_at", "datetime", comment="创建时间", index=True, nullable=False),
                    _column("updated_at", "datetime", comment="更新时间", index=True, nullable=False),
                ],
            ),
            TableInfo(
                database=DEMO_DATABASE,
                name="payment_callback",
                comment="支付回调记录",
                engine="demo",
                row_count_approx=4,
                column=[
                    _column("callback_id", "varchar(32)", comment="回调 ID", primary=True, nullable=False),
                    _column("order_id", "varchar(32)", comment="订单号", index=True, nullable=False),
                    _column("channel", "varchar(24)", comment="支付渠道", index=True, nullable=False),
                    _column("status", "varchar(24)", comment="回调状态", index=True, nullable=False),
                    _column("retry_count", "int", comment="重试次数", nullable=False),
                    _column("last_error", "varchar(255)", comment="最近错误"),
                    _column("received_at", "datetime", comment="收到时间", index=True, nullable=False),
                    _column("processed_at", "datetime", comment="处理完成时间", index=True),
                ],
            ),
            TableInfo(
                database=DEMO_DATABASE,
                name="users",
                comment="用户账户",
                engine="demo",
                row_count_approx=3,
                column=[
                    _column("user_id", "varchar(32)", comment="用户 ID", primary=True, nullable=False),
                    _column("phone", "varchar(20)", comment="手机号", index=True),
                    _column("tier", "varchar(16)", comment="用户等级", index=True),
                    _column("status", "varchar(16)", comment="账户状态", index=True),
                    _column("created_at", "datetime", comment="注册时间", index=True),
                ],
            ),
        ],
    )


def build_demo_services() -> list[ServiceInfo]:
    return [
        ServiceInfo(
            name="gateway",
            status="RUNNING",
            pid=1101,
            deploy_path="/srv/demo/gateway",
            log_path="/var/log/demo/gateway.log",
            database_list=[DEMO_DATABASE],
        ),
        ServiceInfo(
            name="order-service",
            status="RUNNING",
            pid=1201,
            deploy_path="/srv/demo/order-service",
            log_path="/var/log/demo/order-service.log",
            database_list=[DEMO_DATABASE],
        ),
        ServiceInfo(
            name="payment-callback",
            status="RUNNING",
            pid=1301,
            deploy_path="/srv/demo/payment-callback",
            log_path="/var/log/demo/payment-callback.log",
            database_list=[DEMO_DATABASE],
        ),
    ]


async def seed_demo() -> dict:
    from app.services import schema_service, service_discovery

    snapshot = build_demo_snapshot()
    snapshots = schema_service._snapshots.setdefault(DEMO_DATABASE, [])
    snapshots.append(snapshot)
    schema_service._snapshots[DEMO_DATABASE] = snapshots[-10:]

    services = build_demo_services()
    service_discovery.upsert_services(services)

    return {
        "database": DEMO_DATABASE,
        "table_count": len(snapshot.table),
        "service_count": len(services),
        "tables": [table.name for table in snapshot.table],
    }
