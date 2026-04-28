"""语义自动推断 — 根据字段名、类型、注释推断业务含义

三层语义模型的第一层（自动推断）和第二层（规则增强）。
第三层（人工标注）通过 Console 界面完成。
"""

import re

# ── 第一层：常见字段名 → 语义映射 ──────────────

_FIELD_SEMANTIC_MAP: dict[str, str] = {
    "id": "主键ID",
    "created_at": "创建时间",
    "updated_at": "更新时间",
    "deleted_at": "删除时间（软删除）",
    "create_time": "创建时间",
    "update_time": "更新时间",
    "status": "状态",
    "name": "名称",
    "title": "标题",
    "description": "描述",
    "remark": "备注",
    "amount": "金额",
    "price": "价格",
    "quantity": "数量",
    "total": "总计",
    "phone": "手机号",
    "mobile": "手机号",
    "email": "邮箱",
    "address": "地址",
    "user_id": "用户ID",
    "order_id": "订单ID",
    "order_no": "订单号",
    "trade_no": "交易号",
    "request_id": "请求ID",
    "trace_id": "链路追踪ID",
    "is_deleted": "是否已删除",
    "is_active": "是否激活",
    "sort": "排序",
    "sort_order": "排序顺序",
    "type": "类型",
    "category": "分类",
    "level": "级别",
    "version": "版本号",
}


# ── 第二层：命名模式规则 ──────────────

_PATTERN_RULES: list[tuple[str, str]] = [
    (r".*_id$", "关联ID"),
    (r".*_no$", "编号"),
    (r".*_code$", "编码"),
    (r".*_name$", "名称"),
    (r".*_time$", "时间"),
    (r".*_date$", "日期"),
    (r".*_at$", "时间"),
    (r".*_count$", "计数"),
    (r".*_num$", "数量"),
    (r".*_amount$", "金额"),
    (r".*_price$", "价格"),
    (r".*_rate$", "比率"),
    (r".*_ratio$", "比例"),
    (r".*_url$", "链接地址"),
    (r".*_path$", "路径"),
    (r".*_key$", "键"),
    (r".*_token$", "令牌"),
    (r".*_flag$", "标记"),
    (r".*_status$", "状态"),
    (r".*_type$", "类型"),
    (r"^is_.*$", "布尔标记"),
    (r"^has_.*$", "布尔标记"),
    (r"^can_.*$", "布尔标记"),
]


def infer_semantic(field_name: str, field_type: str, comment: str) -> str:
    """推断字段语义

    优先级：MySQL 注释 > 精确匹配 > 模式规则 > 空
    """
    # MySQL 注释不为空，直接用
    if comment and comment.strip():
        return comment.strip()

    name_lower = field_name.lower()

    # 精确匹配
    if name_lower in _FIELD_SEMANTIC_MAP:
        return _FIELD_SEMANTIC_MAP[name_lower]

    # 模式规则匹配
    for pattern, semantic in _PATTERN_RULES:
        if re.match(pattern, name_lower):
            # 尝试提取前缀作为更具体的描述
            prefix = re.sub(r"_(id|no|code|name|time|date|at|count|num|amount|price|rate|url|path|status|type|flag)$", "", name_lower)
            if prefix and prefix != name_lower:
                return f"{prefix} {semantic}"
            return semantic

    return ""
