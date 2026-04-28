#!/usr/bin/env python3
"""
Meridian 本地冒烟测试

用法:
    uv run scripts/smoke-test.py              # 测试所有可用服务
    uv run scripts/smoke-test.py atlas        # 只测 Atlas
    uv run scripts/smoke-test.py --mysql      # 只测 MySQL 连通性
    uv run scripts/smoke-test.py --pg         # 只测 PostgreSQL 连通性

这个脚本不依赖项目代码，直接用标准库 + 原始连接测试，
方便 AI 和开发者快速验证本地环境是否可用。
"""

import json
import socket
import sys
import urllib.request
import urllib.error


# ── 配置 ──────────────────────────────────────

SERVICES = {
    "nexus": {"port": 3000, "health": "/health"},
    "atlas": {"port": 3001, "health": "/health"},
    "probe": {"port": 3002, "health": "/health"},
    "lens":  {"port": 3003, "health": "/health"},
    "trace": {"port": 3004, "health": "/health"},
}

MYSQL_CONFIG = {
    "host": "127.0.0.1",
    "port": 3306,
    "user": "root",
    "password": "root",
}

PG_CONFIG = {
    "host": "127.0.0.1",
    "port": 15432,
}


# ── 测试函数 ──────────────────────────────────

def check_port(host: str, port: int, timeout: float = 2.0) -> bool:
    """检查端口是否可达"""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (ConnectionRefusedError, TimeoutError, OSError):
        return False


def check_http(port: int, path: str) -> dict:
    """检查 HTTP 端点"""
    url = f"http://127.0.0.1:{port}{path}"
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = resp.read().decode()
            return {"ok": True, "status": resp.status, "body": body[:200]}
    except urllib.error.URLError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def check_mysql() -> dict:
    """测试 MySQL 连通性（只检查端口 + 尝试连接）"""
    cfg = MYSQL_CONFIG
    if not check_port(cfg["host"], cfg["port"]):
        return {"ok": False, "error": f"端口 {cfg['port']} 不可达"}

    try:
        import pymysql
        conn = pymysql.connect(
            host=cfg["host"], port=cfg["port"],
            user=cfg["user"], password=cfg["password"],
            database="information_schema",
            connect_timeout=5,
        )
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM TABLES WHERE TABLE_SCHEMA NOT IN ('mysql','sys','performance_schema','information_schema')")
            count = cur.fetchone()[0]
        conn.close()
        return {"ok": True, "user_tables": count}
    except ImportError:
        # 没装 pymysql，用 aiomysql 试试
        try:
            import aiomysql
            return {"ok": True, "note": "端口可达，aiomysql 可用（需要 async 环境验证连接）"}
        except ImportError:
            return {"ok": True, "note": "端口可达，但未安装 pymysql/aiomysql，无法验证认证"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def check_pg() -> dict:
    """测试 PostgreSQL 连通性"""
    cfg = PG_CONFIG
    if not check_port(cfg["host"], cfg["port"]):
        return {"ok": False, "error": f"端口 {cfg['port']} 不可达（Atlas 会以纯内存模式运行）"}
    return {"ok": True, "note": "端口可达"}


def check_mcp_tools(port: int) -> dict:
    """检查 MCP SSE 端点是否可用"""
    url = f"http://127.0.0.1:{port}/mcp/sse"
    try:
        req = urllib.request.Request(url, method="GET")
        # SSE 会挂起，只测 connect
        with urllib.request.urlopen(req, timeout=3) as resp:
            return {"ok": True, "status": resp.status}
    except urllib.error.URLError:
        return {"ok": False, "note": "SSE 端点不可达"}
    except Exception:
        # timeout 也算成功（说明端点在，只是 SSE 长连接）
        return {"ok": True, "note": "SSE 端点可达（长连接超时，预期行为）"}


# ── 主逻辑 ──────────────────────────────────

def main():
    args = sys.argv[1:]

    results = {}
    ok_count = 0
    fail_count = 0

    def record(name: str, result: dict):
        nonlocal ok_count, fail_count
        status = "✅" if result.get("ok") else "❌"
        if result.get("ok"):
            ok_count += 1
        else:
            fail_count += 1
        results[name] = result
        detail = json.dumps({k: v for k, v in result.items() if k != "ok"}, ensure_ascii=False)
        print(f"  {status} {name}: {detail}")

    # MySQL 测试
    if not args or "--mysql" in args:
        print("\n🗄️  MySQL 连通性")
        record("mysql", check_mysql())

    # PostgreSQL 测试
    if not args or "--pg" in args:
        print("\n🐘 PostgreSQL 连通性")
        record("postgresql", check_pg())

    # 服务测试
    target_services = [a for a in args if a in SERVICES] if args else list(SERVICES.keys())
    if target_services or not args:
        print("\n🌐 服务健康检查")
        for svc in (target_services or SERVICES.keys()):
            cfg = SERVICES[svc]
            if not check_port("127.0.0.1", cfg["port"]):
                record(f"{svc} (port {cfg['port']})", {"ok": False, "error": "未启动"})
                continue
            record(f"{svc} /health", check_http(cfg["port"], cfg["health"]))
            record(f"{svc} /", check_http(cfg["port"], "/"))
            record(f"{svc} /mcp/sse", check_mcp_tools(cfg["port"]))

    # 汇总
    print(f"\n{'='*50}")
    print(f"总计: {ok_count} 通过, {fail_count} 失败")

    if fail_count > 0:
        print("\n💡 提示:")
        if results.get("mysql", {}).get("ok") is False:
            print("  - MySQL: 确认 local-mysql 容器在运行 (docker ps)")
        if results.get("postgresql", {}).get("ok") is False:
            print("  - PostgreSQL: 未运行，Atlas 会以纯内存模式工作（不影响基本功能）")
        for svc in target_services or SERVICES.keys():
            key = f"{svc} /health"
            if results.get(key, {}).get("ok") is False:
                print(f"  - {svc}: 用 ./scripts/dev.sh {svc} 启动")

    return 1 if fail_count > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
