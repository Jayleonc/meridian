#!/usr/bin/env python3
"""Local interactive Agent CLI for testing Nexus MCP tools.

This script is intentionally dependency-free. It speaks MCP StreamableHTTP to
Nexus, then calls the `probe.*` and read-only `devops.*` tools exposed by the
gateway.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


DEFAULT_NEXUS_URL = "http://127.0.0.1:3000"
PROTOCOL_VERSION = "2025-04-28"


class CliError(RuntimeError):
    pass


@dataclass
class ToolCommand:
    name: str
    arguments: dict[str, Any]


class NexusMCPClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.endpoint = f"{self.base_url}/mcp/stream/"
        self.session_id: str | None = None
        self._next_id = 1

    def initialize(self) -> None:
        result, headers = self._rpc(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "meridian-agent-cli", "version": "0.1.0"},
            },
            include_session=False,
        )
        session_id = headers.get("mcp-session-id")
        if not session_id:
            raise CliError("Nexus did not return mcp-session-id")
        self.session_id = session_id
        self._notify("notifications/initialized", {})
        server_info = result.get("serverInfo", {})
        print(f"Connected to Nexus MCP: {server_info.get('name', 'unknown')}")

    def list_tools(self) -> list[dict[str, Any]]:
        result, _headers = self._rpc("tools/list", {})
        return result.get("tools", [])

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        result, _headers = self._rpc(
            "tools/call",
            {"name": name, "arguments": arguments},
        )
        if result.get("isError"):
            return {"error": "tool_error", "detail": result}

        content = result.get("content") or []
        if content and content[0].get("type") == "text":
            return _parse_jsonish(content[0].get("text", ""))

        structured = result.get("structuredContent")
        if structured and "result" in structured:
            return _parse_jsonish(structured["result"])

        return result

    def get_json(self, path: str) -> Any:
        url = f"{self.base_url}{path}"
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise CliError(f"GET {url} failed: {exc}") from exc

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        self._post_json({"jsonrpc": "2.0", "method": method, "params": params})

    def _rpc(
        self,
        method: str,
        params: dict[str, Any],
        *,
        include_session: bool = True,
    ) -> tuple[dict[str, Any], Any]:
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id,
            "method": method,
            "params": params,
        }
        self._next_id += 1
        data, headers = self._post_json(payload, include_session=include_session)
        if "error" in data:
            raise CliError(json.dumps(data["error"], ensure_ascii=False))
        return data.get("result", {}), headers

    def _post_json(
        self,
        payload: dict[str, Any],
        *,
        include_session: bool = True,
    ) -> tuple[dict[str, Any], Any]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if include_session:
            if not self.session_id:
                raise CliError("MCP session is not initialized")
            headers["mcp-session-id"] = self.session_id

        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.endpoint,
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as resp:
                raw = resp.read().decode("utf-8")
                if not raw:
                    return {}, resp.headers
                return _parse_response_body(raw), resp.headers
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise CliError(f"MCP HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise CliError(f"Cannot connect to Nexus at {self.endpoint}: {exc}") from exc


def _parse_response_body(raw: str) -> dict[str, Any]:
    raw = raw.strip()
    if raw.startswith("event:") or raw.startswith("data:"):
        data_lines = []
        for line in raw.splitlines():
            if line.startswith("data:"):
                data_lines.append(line.removeprefix("data:").strip())
        raw = "\n".join(data_lines)
    return json.loads(raw)


def _parse_jsonish(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return text
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _pretty(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def _parse_int(text: str, default: int) -> int:
    try:
        return int(text)
    except (TypeError, ValueError):
        return default


def parse_command(line: str) -> ToolCommand | str | None:
    text = line.strip()
    if not text:
        return None

    lower = text.lower()
    if lower in {"/quit", "quit", "exit", "q", "退出"}:
        return "quit"
    if lower in {"/help", "help", "?", "帮助"}:
        return "help"
    if lower in {"/tools", "tools", "工具"}:
        return "tools"
    if lower in {"/health", "health", "健康"}:
        return "health"
    if lower in {"/registry", "registry", "注册表"}:
        return "registry"
    if lower in {"/services", "services", "服务", "有哪些服务", "列出服务"}:
        return ToolCommand("probe.list_services", {})
    if lower in {"/devops", "devops", "运行状态", "运行情况"}:
        return ToolCommand("devops.runtime_status", {})
    if lower in {"/smoke", "smoke", "冒烟"}:
        return ToolCommand("devops.smoke_test", {})
    if lower in {"/config", "config", "配置检查"}:
        return ToolCommand("devops.config_check", {})
    if lower in {"/logfiles", "logfiles", "日志文件"}:
        return ToolCommand("devops.list_service_logs", {})

    if lower.startswith("/call "):
        return _parse_raw_call(text)
    if lower.startswith("/logs"):
        return _parse_devops_logs(text)
    if lower.startswith("/errors") or "最近错误" in text or "报错" in text:
        return _parse_errors(text)
    if lower.startswith("/search "):
        return ToolCommand("probe.search_logs", {"keyword": text.split(" ", 1)[1]})
    if text.startswith("搜索 "):
        return ToolCommand("probe.search_logs", {"keyword": text.split(" ", 1)[1]})
    if text.startswith("查日志 "):
        return ToolCommand("probe.search_logs", {"keyword": text.split(" ", 1)[1]})
    if lower.startswith("/trace "):
        return _parse_trace(text)
    if lower.startswith("/context "):
        return _parse_context(text)

    request_id = _extract_request_id(text)
    if request_id:
        return ToolCommand("probe.search_by_request_id", {"request_id": request_id})

    return ToolCommand("probe.search_logs", {"keyword": text})


def _parse_raw_call(text: str) -> ToolCommand:
    parts = text.split(" ", 2)
    if len(parts) < 2:
        raise CliError("用法: /call <tool_name> {json_arguments}")
    args: dict[str, Any] = {}
    if len(parts) == 3:
        parsed = json.loads(parts[2])
        if not isinstance(parsed, dict):
            raise CliError("/call 的参数必须是 JSON object")
        args = parsed
    return ToolCommand(parts[1], args)


def _parse_devops_logs(text: str) -> ToolCommand:
    parts = text.split()
    service = parts[1] if len(parts) >= 2 else "nexus"
    lines = _parse_int(parts[2], 120) if len(parts) >= 3 else 120
    return ToolCommand("devops.tail_service_log", {"service": service, "lines": lines})


def _parse_errors(text: str) -> ToolCommand:
    parts = text.split()
    hours = 1
    keyword_parts: list[str] = []
    if len(parts) >= 2 and parts[0].lower() == "/errors":
        hours = _parse_int(parts[1], 1)
        keyword_parts = parts[2:] if parts[1].isdigit() else parts[1:]
    args: dict[str, Any] = {"hours_back": hours, "limit": 30}
    if keyword_parts:
        args["keyword"] = " ".join(keyword_parts)
    return ToolCommand("probe.tail_errors", args)


def _parse_trace(text: str) -> ToolCommand:
    parts = text.split()
    if len(parts) < 2:
        raise CliError("用法: /trace <request_id> [back_hours]")
    args: dict[str, Any] = {"request_id": parts[1]}
    if len(parts) >= 3:
        args["back_hours"] = _parse_int(parts[2], 0)
    return ToolCommand("probe.search_by_request_id", args)


def _parse_context(text: str) -> ToolCommand:
    parts = text.split()
    if len(parts) < 3:
        raise CliError("用法: /context <file> <line_number> [before] [after]")
    return ToolCommand(
        "probe.context_around_match",
        {
            "file": parts[1],
            "line_number": _parse_int(parts[2], 1),
            "before": _parse_int(parts[3], 10) if len(parts) >= 4 else 10,
            "after": _parse_int(parts[4], 10) if len(parts) >= 5 else 10,
        },
    )


def _extract_request_id(text: str) -> str | None:
    if not re.search(r"request|请求|req[_ -]?id", text, re.IGNORECASE):
        return None
    candidates = re.findall(r"[A-Za-z0-9][A-Za-z0-9_.-]{7,}", text)
    ignored = {"request_id", "request-id", "requestid"}
    for candidate in candidates:
        if candidate.lower() not in ignored:
            return candidate
    return None


def print_help() -> None:
    print(
        """
可用命令:
  /tools                         列出 Nexus 暴露的 MCP tools
  /health                        查看 Nexus 聚合健康状态
  /registry                      查看 Nexus 注册表
  /devops                        查看 Meridian 自身运行状态
  /logfiles                      列出 dev-server 生成的服务日志文件
  /logs [service] [lines]        读取服务日志，如 /logs nexus 120
  /smoke                         执行只读 smoke test
  /config                        检查关键配置（不显示密钥）
  /services                      调 probe.list_services
  /errors [hours] [keyword]      调 probe.tail_errors
  /search <keyword>              调 probe.search_logs
  /trace <request_id> [hours]    调 probe.search_by_request_id
  /context <file> <line>         调 probe.context_around_match
  /call <tool> {json}            原始 MCP tools/call
  /quit                          退出

自然语言快捷方式:
  最近错误日志
  有哪些服务
  搜索 timeout
  查 request_id 7n8dpbl2SRiZmnpytX4A

未识别的普通输入会默认当作日志关键词搜索。
""".strip()
    )


def run_command(client: NexusMCPClient, line: str) -> bool:
    parsed = parse_command(line)
    if parsed is None:
        return True
    if parsed == "quit":
        return False
    if parsed == "help":
        print_help()
        return True
    if parsed == "tools":
        tools = client.list_tools()
        for tool in tools:
            print(f"- {tool.get('name')}: {tool.get('description', '')}")
        return True
    if parsed == "health":
        print(_pretty(client.get_json("/health")))
        return True
    if parsed == "registry":
        print(_pretty(client.get_json("/registry")))
        return True
    if isinstance(parsed, ToolCommand):
        print(f"> {parsed.name} {json.dumps(parsed.arguments, ensure_ascii=False)}")
        result = client.call_tool(parsed.name, parsed.arguments)
        print(_pretty(result))
        return True
    raise CliError(f"Unknown parsed command: {parsed}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Meridian local Agent CLI")
    parser.add_argument(
        "--nexus-url",
        default=DEFAULT_NEXUS_URL,
        help=f"Nexus base URL, default: {DEFAULT_NEXUS_URL}",
    )
    parser.add_argument(
        "--once",
        help="Run one command and exit, e.g. --once '/services'",
    )
    args = parser.parse_args()

    client = NexusMCPClient(args.nexus_url)
    try:
        client.initialize()
        if args.once:
            run_command(client, args.once)
            return 0

        print("输入 /help 查看命令。Ctrl-D 或 /quit 退出。")
        while True:
            try:
                line = input("meridian> ")
            except EOFError:
                print()
                return 0
            try:
                if not run_command(client, line):
                    return 0
            except (CliError, json.JSONDecodeError) as exc:
                print(f"错误: {exc}", file=sys.stderr)
    except (CliError, json.JSONDecodeError) as exc:
        print(f"启动失败: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
