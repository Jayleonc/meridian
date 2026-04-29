"""MySQL 只读查询守卫测试"""

from app.adapters.mysql_adapter import _readonly_rejection_reason


def test_allows_limited_select():
    assert _readonly_rejection_reason("SELECT * FROM orders LIMIT 10") is None


def test_rejects_non_select():
    assert _readonly_rejection_reason("UPDATE orders SET status = 1 LIMIT 1") is not None


def test_rejects_multi_statement():
    sql = "SELECT * FROM orders LIMIT 1; UPDATE orders SET status = 1"
    assert _readonly_rejection_reason(sql) is not None


def test_rejects_select_without_limit():
    assert _readonly_rejection_reason("SELECT * FROM orders") is not None


def test_rejects_mutating_keyword_inside_select():
    sql = "SELECT * FROM orders WHERE note = 'UPDATE user' LIMIT 1"
    assert _readonly_rejection_reason(sql) is not None
