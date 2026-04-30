"""DSL 编译器单元测试"""

import pytest

from app.schemas.query import (
    EntityConstraint,
    EntityDefinition,
    EntityField,
    FilterCondition,
    QueryDSL,
)
from app.services.dsl_compiler import compile_to_sql, validate_dsl


# ── 测试用 entity ──────────────────────────────

def _make_order_entity() -> EntityDefinition:
    """构造一个测试用的 order entity。"""
    return EntityDefinition(
        name="order",
        display_name="订单",
        database="test",
        source_table=["order"],
        primary_table="order",
        fields={
            "order_id": EntityField(
                name="order_id", column="order_id", type="varchar(64)",
                semantic="订单号", filterable=True, sortable=True,
            ),
            "status": EntityField(
                name="status", column="status", type="int",
                semantic="订单状态", filterable=True, sortable=True,
            ),
            "amount": EntityField(
                name="amount", column="amount", type="decimal(10,2)",
                semantic="订单金额", filterable=True, sortable=True,
            ),
            "created_at": EntityField(
                name="created_at", column="created_at", type="datetime",
                semantic="创建时间", filterable=True, sortable=True,
            ),
            "phone": EntityField(
                name="phone", column="phone", type="varchar(20)",
                semantic="手机号", filterable=False, sortable=False,
                sensitive=True, default_visible=False,
            ),
        },
        constraint=EntityConstraint(
            time_field="created_at",
            default_time_range_days=7,
            required_filter_fields=[],
        ),
    )


# ── validate_dsl 测试 ──────────────────────────


class TestValidateDSL:
    def test_valid_query(self):
        entity = _make_order_entity()
        dsl = QueryDSL(
            entity="order",
            filter=[FilterCondition(field="order_id", op="eq", value="123")],
            limit=10,
        )
        result = validate_dsl(dsl, entity)
        assert result.valid is True
        assert result.errors == []

    def test_missing_filter(self):
        entity = _make_order_entity()
        dsl = QueryDSL(entity="order", filter=[], limit=10)
        result = validate_dsl(dsl, entity)
        assert result.valid is False
        assert any("筛选条件" in e for e in result.errors)

    def test_unknown_filter_field(self):
        entity = _make_order_entity()
        dsl = QueryDSL(
            entity="order",
            filter=[FilterCondition(field="nonexistent", op="eq", value="x")],
        )
        result = validate_dsl(dsl, entity)
        assert result.valid is False
        assert any("不存在" in e for e in result.errors)

    def test_unfilterable_field(self):
        entity = _make_order_entity()
        dsl = QueryDSL(
            entity="order",
            filter=[FilterCondition(field="phone", op="eq", value="123")],
        )
        result = validate_dsl(dsl, entity)
        assert result.valid is False
        assert any("不可筛选" in e for e in result.errors)

    def test_invalid_operator(self):
        entity = _make_order_entity()
        dsl = QueryDSL(
            entity="order",
            filter=[FilterCondition(field="order_id", op="regex", value=".*")],
        )
        result = validate_dsl(dsl, entity)
        assert result.valid is False
        assert any("不支持的操作符" in e for e in result.errors)

    def test_unknown_return_field(self):
        entity = _make_order_entity()
        dsl = QueryDSL(
            entity="order",
            filter=[FilterCondition(field="order_id", op="eq", value="1")],
            field=["nonexistent"],
        )
        result = validate_dsl(dsl, entity)
        assert result.valid is False

    def test_unsortable_field(self):
        entity = _make_order_entity()
        dsl = QueryDSL(
            entity="order",
            filter=[FilterCondition(field="order_id", op="eq", value="1")],
            order_by="phone",
        )
        result = validate_dsl(dsl, entity)
        assert result.valid is False


# ── compile_to_sql 测试 ────────────────────────


class TestCompileToSQL:
    def test_basic_eq_filter(self):
        entity = _make_order_entity()
        dsl = QueryDSL(
            entity="order",
            filter=[FilterCondition(field="order_id", op="eq", value="ORD001")],
            limit=10,
        )
        sql, params = compile_to_sql(dsl, entity)
        assert "SELECT" in sql
        assert "`order_id` = %s" in sql
        assert "LIMIT 10" in sql
        assert params[0] == "ORD001"

    def test_in_filter(self):
        entity = _make_order_entity()
        dsl = QueryDSL(
            entity="order",
            filter=[FilterCondition(field="status", op="in", value=[1, 2, 3])],
            limit=5,
        )
        sql, params = compile_to_sql(dsl, entity)
        assert "IN (%s, %s, %s)" in sql
        assert list(params[:3]) == [1, 2, 3]

    def test_order_by_desc(self):
        entity = _make_order_entity()
        dsl = QueryDSL(
            entity="order",
            filter=[FilterCondition(field="order_id", op="eq", value="1")],
            order_by="-created_at",
            limit=10,
        )
        sql, params = compile_to_sql(dsl, entity)
        assert "`created_at` DESC" in sql

    def test_sensitive_field_masked(self):
        entity = _make_order_entity()
        dsl = QueryDSL(
            entity="order",
            filter=[FilterCondition(field="order_id", op="eq", value="1")],
            field=["order_id", "phone"],
            limit=10,
        )
        sql, params = compile_to_sql(dsl, entity)
        assert "CONCAT(LEFT(phone, 3), '****')" in sql

    def test_limit_capped(self):
        entity = _make_order_entity()
        dsl = QueryDSL(
            entity="order",
            filter=[FilterCondition(field="order_id", op="eq", value="1")],
            limit=100,
        )
        sql, params = compile_to_sql(dsl, entity)
        assert "LIMIT 100" in sql

    def test_from_with_database(self):
        entity = _make_order_entity()
        dsl = QueryDSL(
            entity="order",
            filter=[FilterCondition(field="order_id", op="eq", value="1")],
            limit=5,
        )
        sql, params = compile_to_sql(dsl, entity)
        assert "`test`.`order`" in sql

    def test_like_filter(self):
        entity = _make_order_entity()
        dsl = QueryDSL(
            entity="order",
            filter=[FilterCondition(field="order_id", op="like", value="ORD")],
            limit=10,
        )
        sql, params = compile_to_sql(dsl, entity)
        assert "`order_id` LIKE %s" in sql
        assert "%ORD%" in params

    def test_auto_time_range(self):
        """不指定 time_range 时，应自动追加时间约束。"""
        entity = _make_order_entity()
        dsl = QueryDSL(
            entity="order",
            filter=[FilterCondition(field="order_id", op="eq", value="1")],
            limit=10,
        )
        sql, params = compile_to_sql(dsl, entity)
        assert "`created_at` >= %s" in sql

    def test_count_aggregate(self):
        entity = _make_order_entity()
        dsl = QueryDSL(
            entity="order",
            filter=[FilterCondition(field="status", op="eq", value=1)],
            aggregate="count",
            order_by="-created_at",
            limit=10,
        )
        sql, params = compile_to_sql(dsl, entity)
        assert "SELECT COUNT(*) AS count" in sql
        assert "ORDER BY" not in sql
        assert "LIMIT 1" in sql
        assert params[0] == 1


# ── PostgreSQL 方言测试 ────────────────────────


def _make_pg_entity() -> EntityDefinition:
    """构造一个 PostgreSQL 的测试 entity。"""
    return EntityDefinition(
        name="document",
        display_name="文档",
        database="",
        db_type="postgresql",
        source_table=["document"],
        primary_table="document",
        fields={
            "id": EntityField(
                name="id", column="id", type="uuid",
                semantic="文档ID", filterable=True, sortable=True,
            ),
            "title": EntityField(
                name="title", column="title", type="varchar",
                semantic="标题", filterable=True, sortable=True,
            ),
            "status": EntityField(
                name="status", column="status", type="int",
                semantic="状态", filterable=True, sortable=True,
            ),
            "created_at": EntityField(
                name="created_at", column="created_at", type="timestamptz",
                semantic="创建时间", filterable=True, sortable=True,
            ),
            "author_phone": EntityField(
                name="author_phone", column="author_phone", type="varchar",
                semantic="作者手机号", filterable=False, sortable=False,
                sensitive=True, default_visible=False,
            ),
        },
        constraint=EntityConstraint(
            time_field="created_at",
            default_time_range_days=7,
            required_filter_fields=[],
        ),
    )


class TestPostgreSQLDialect:
    def test_pg_placeholder(self):
        """PG 应使用 $1, $2... 占位符"""
        entity = _make_pg_entity()
        dsl = QueryDSL(
            entity="document",
            filter=[FilterCondition(field="id", op="eq", value="abc-123")],
            limit=10,
        )
        sql, params = compile_to_sql(dsl, entity)
        assert '"id" = $1' in sql
        assert "$1" in sql
        assert "%s" not in sql
        assert params[0] == "abc-123"

    def test_pg_double_quote_identifiers(self):
        """PG 应使用双引号标识符"""
        entity = _make_pg_entity()
        dsl = QueryDSL(
            entity="document",
            filter=[FilterCondition(field="title", op="eq", value="test")],
            limit=5,
        )
        sql, params = compile_to_sql(dsl, entity)
        assert '"document"' in sql
        assert '"title"' in sql
        # 不应有 backtick
        assert "`" not in sql

    def test_pg_in_filter(self):
        """PG IN 子句应使用 $N 占位符"""
        entity = _make_pg_entity()
        dsl = QueryDSL(
            entity="document",
            filter=[FilterCondition(field="status", op="in", value=[1, 2, 3])],
            limit=5,
        )
        sql, params = compile_to_sql(dsl, entity)
        assert "IN ($1, $2, $3)" in sql
        assert list(params[:3]) == [1, 2, 3]

    def test_pg_sensitive_mask(self):
        """PG 敏感字段脱敏应使用 ::text 转换"""
        entity = _make_pg_entity()
        dsl = QueryDSL(
            entity="document",
            filter=[FilterCondition(field="id", op="eq", value="1")],
            field=["id", "author_phone"],
            limit=10,
        )
        sql, params = compile_to_sql(dsl, entity)
        assert "::text" in sql
        assert "CONCAT(LEFT(author_phone::text, 3), '****')" in sql

    def test_pg_order_by(self):
        """PG ORDER BY 应使用双引号"""
        entity = _make_pg_entity()
        dsl = QueryDSL(
            entity="document",
            filter=[FilterCondition(field="id", op="eq", value="1")],
            order_by="-created_at",
            limit=10,
        )
        sql, params = compile_to_sql(dsl, entity)
        assert '"created_at" DESC' in sql

    def test_pg_auto_time_range(self):
        """PG 时间范围应使用 $N 占位符"""
        entity = _make_pg_entity()
        dsl = QueryDSL(
            entity="document",
            filter=[FilterCondition(field="id", op="eq", value="1")],
            limit=10,
        )
        sql, params = compile_to_sql(dsl, entity)
        assert '"created_at" >= $2' in sql

    def test_pg_multiple_filters(self):
        """多个筛选条件的参数索引应连续递增"""
        entity = _make_pg_entity()
        dsl = QueryDSL(
            entity="document",
            filter=[
                FilterCondition(field="id", op="eq", value="abc"),
                FilterCondition(field="status", op="gt", value=1),
                FilterCondition(field="title", op="like", value="test"),
            ],
            limit=10,
        )
        sql, params = compile_to_sql(dsl, entity)
        assert "$1" in sql
        assert "$2" in sql
        assert "$3" in sql
        assert len(params) >= 3
