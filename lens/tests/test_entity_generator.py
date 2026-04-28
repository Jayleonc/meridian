"""entity_generator 单元测试 — 验证从 schema 自动生成 entity 定义的逻辑"""

import pytest

from app.services.entity_generator import (
    generate_entity_from_table,
    _detect_type,
    _is_sensitive,
    _detect_time_field,
    _is_filterable,
)


# ── 类型检测 ──

class TestDetectType:
    def test_int_types(self):
        assert _detect_type("bigint") == "int"
        assert _detect_type("int") == "int"
        assert _detect_type("tinyint(1)") == "int"
        assert _detect_type("mediumint") == "int"

    def test_decimal_types(self):
        assert _detect_type("decimal(10,2)") == "decimal"
        assert _detect_type("float") == "decimal"
        assert _detect_type("double") == "decimal"

    def test_datetime_types(self):
        assert _detect_type("datetime") == "datetime"
        assert _detect_type("timestamp") == "datetime"
        assert _detect_type("date") == "datetime"

    def test_string_types(self):
        assert _detect_type("varchar(255)") == "string"
        assert _detect_type("char(32)") == "string"
        assert _detect_type("text") == "string"
        assert _detect_type("enum('a','b')") == "string"


# ── 敏感字段检测 ──

class TestIsSensitive:
    def test_sensitive_fields(self):
        assert _is_sensitive("phone") is True
        assert _is_sensitive("user_phone") is True
        assert _is_sensitive("mobile_number") is True
        assert _is_sensitive("id_card") is True
        assert _is_sensitive("password") is True
        assert _is_sensitive("secret_key") is True

    def test_normal_fields(self):
        assert _is_sensitive("username") is False
        assert _is_sensitive("created_at") is False
        assert _is_sensitive("status") is False
        assert _is_sensitive("order_id") is False


# ── 时间字段检测 ──

class TestDetectTimeField:
    def test_created_at(self):
        cols = [
            {"name": "id", "type": "bigint"},
            {"name": "created_at", "type": "datetime"},
            {"name": "name", "type": "varchar(64)"},
        ]
        assert _detect_time_field(cols) == "created_at"

    def test_create_time(self):
        cols = [
            {"name": "id", "type": "bigint"},
            {"name": "create_time", "type": "datetime"},
        ]
        assert _detect_time_field(cols) == "create_time"

    def test_gmt_create(self):
        cols = [
            {"name": "id", "type": "bigint"},
            {"name": "gmt_create", "type": "datetime"},
        ]
        assert _detect_time_field(cols) == "gmt_create"

    def test_fallback_to_datetime_type(self):
        """没有常见名称时，退而求其次找 datetime 类型"""
        cols = [
            {"name": "id", "type": "bigint"},
            {"name": "log_ts", "type": "timestamp"},
        ]
        assert _detect_time_field(cols) == "log_ts"

    def test_no_time_field(self):
        cols = [
            {"name": "id", "type": "bigint"},
            {"name": "name", "type": "varchar(64)"},
        ]
        assert _detect_time_field(cols) == ""


# ── 可过滤检测 ──

class TestIsFilterable:
    def test_pk_is_filterable(self):
        assert _is_filterable({"name": "id", "type": "bigint", "is_primary_key": True}) is True

    def test_index_is_filterable(self):
        assert _is_filterable({"name": "user_id", "type": "bigint", "is_index": True}) is True

    def test_short_varchar_is_filterable(self):
        assert _is_filterable({"name": "status", "type": "varchar(32)"}) is True
        assert _is_filterable({"name": "code", "type": "varchar(64)"}) is True

    def test_long_varchar_not_filterable(self):
        assert _is_filterable({"name": "description", "type": "varchar(500)"}) is False

    def test_plain_bigint_not_filterable(self):
        assert _is_filterable({"name": "amount", "type": "bigint"}) is False


# ── 完整生成 ──

class TestGenerateEntity:
    def test_basic_table(self):
        columns = [
            {"name": "id", "type": "bigint", "is_primary_key": True, "is_index": True, "nullable": False, "comment": "主键"},
            {"name": "username", "type": "varchar(64)", "is_primary_key": False, "is_index": True, "nullable": False, "comment": "用户名"},
            {"name": "phone", "type": "varchar(20)", "is_primary_key": False, "is_index": False, "nullable": True, "comment": "手机号"},
            {"name": "amount", "type": "decimal(10,2)", "is_primary_key": False, "is_index": False, "nullable": True, "comment": "金额"},
            {"name": "status", "type": "varchar(16)", "is_primary_key": False, "is_index": True, "nullable": False, "comment": "状态"},
            {"name": "created_at", "type": "datetime", "is_primary_key": False, "is_index": False, "nullable": True, "comment": "创建时间"},
            {"name": "bio", "type": "text", "is_primary_key": False, "is_index": False, "nullable": True, "comment": "简介"},
        ]

        result = generate_entity_from_table(
            database="test",
            table_name="user",
            columns=columns,
        )

        # Name convention
        assert result["name"] == "test__user"
        assert result["database"] == "test"
        assert result["primary_table"] == "user"

        fields = result["fields"]
        assert len(fields) == 7

        # PK is filterable
        assert fields["id"]["filterable"] is True
        assert fields["id"]["type"] == "int"

        # Indexed short varchar is filterable
        assert fields["username"]["filterable"] is True
        assert fields["status"]["filterable"] is True

        # Phone is sensitive
        assert fields["phone"]["sensitive"] is True
        assert fields["phone"]["default_visible"] is False

        # Amount is sortable (decimal)
        assert fields["amount"]["sortable"] is True

        # created_at detected as time_field
        assert result["constraint"]["time_field"] == "created_at"
        assert result["constraint"]["default_time_range_days"] == 7

        # Bio (text) not default_visible
        assert fields["bio"]["default_visible"] is False

    def test_table_without_time_field(self):
        columns = [
            {"name": "id", "type": "bigint", "is_primary_key": True, "is_index": True},
            {"name": "code", "type": "varchar(32)", "is_primary_key": False, "is_index": False},
        ]

        result = generate_entity_from_table(database="test", table_name="config", columns=columns)
        assert result["constraint"]["time_field"] == ""
        assert result["constraint"]["default_time_range_days"] == 0
