from __future__ import annotations

import unittest

from mcp.server.fastmcp import FastMCP

from src.tool_gateway import ToolGateway, _format_path


def _test_registry() -> dict:
    return {
        "atlas": {
            "name": "atlas",
            "base_url": "http://atlas",
            "tool_manifests": [
                {
                    "name": "atlas.health.v1",
                    "adapter": "http",
                    "service": "atlas",
                    "status": "approved",
                    "description": "health",
                    "method": "GET",
                    "path": "/health/{name}",
                    "required_scopes": ["read:health"],
                    "input_schema": {
                        "type": "object",
                        "required": ["name"],
                        "properties": {
                            "name": {"type": "string"},
                            "verbose": {"type": "boolean", "default": False},
                        },
                    },
                    "exposure": {"mcp": True, "agent": False},
                    "timeout_seconds": 1,
                    "max_response_bytes": 1000,
                    "sensitive_fields": ["token"],
                },
                {
                    "name": "atlas.pending.v1",
                    "adapter": "http",
                    "status": "pending",
                    "path": "/pending",
                    "exposure": {"mcp": True},
                },
            ],
        }
    }


class ToolGatewayTest(unittest.IsolatedAsyncioTestCase):
    def test_register_dynamic_tools_uses_manifest_schema_and_skips_pending(self) -> None:
        gateway = ToolGateway(_test_registry(), audit_log_path=None)
        mcp = FastMCP("test")

        registered = gateway.register_dynamic_tools(mcp)

        self.assertEqual(registered, ["atlas.health.v1"])
        tool = mcp._tool_manager.get_tool("atlas.health.v1")
        self.assertIsNotNone(tool)
        self.assertIn("name", tool.parameters["properties"])
        self.assertIn("verbose", tool.parameters["properties"])
        self.assertEqual(tool.parameters["required"], ["name"])
        self.assertIsNone(mcp._tool_manager.get_tool("atlas.pending.v1"))

    async def test_execute_enforces_permissions_before_adapter(self) -> None:
        gateway = ToolGateway(_test_registry(), audit_log_path=None)

        result = await gateway.execute(
            "atlas.health.v1",
            {"name": "svc"},
            caller_scopes=set(),
            trace_id="trace-1",
        )

        self.assertEqual(result["error"], "permission_denied")
        self.assertEqual(result["trace_id"], "trace-1")
        self.assertEqual(gateway.audit_records[-1]["error"], "permission_denied")

    async def test_execute_redacts_truncates_and_audits(self) -> None:
        gateway = ToolGateway(_test_registry(), audit_log_path=None)

        async def fake_adapter(_manifest, _args):
            return {
                "token": "secret-token",
                "line": "x" * 2000,
                "message": "phone=13812345678 token=abc",
            }

        gateway._execute_adapter = fake_adapter
        gateway.manifests["atlas.health.v1"]["max_response_bytes"] = 120

        result = await gateway.execute(
            "atlas.health.v1",
            {"name": "svc", "token": "input-secret"},
            caller_scopes={"read:health"},
            trace_id="trace-2",
        )

        self.assertTrue(result["truncated"])
        self.assertEqual(result["trace_id"], "trace-2")
        self.assertIn("***REDACTED***", result["preview"])
        self.assertEqual(gateway.audit_records[-1]["tool"], "atlas.health.v1")
        self.assertEqual(gateway.audit_records[-1]["parameter"]["token"], "***REDACTED***")

    async def test_dynamic_mcp_handler_executes_pipeline(self) -> None:
        gateway = ToolGateway(_test_registry(), audit_log_path=None)
        mcp = FastMCP("test")
        gateway.register_dynamic_tools(mcp)

        async def fake_adapter(_manifest, args):
            return {"ok": True, "args": args}

        gateway._execute_adapter = fake_adapter

        result = await mcp._tool_manager.call_tool(
            "atlas.health.v1",
            {"name": "svc", "verbose": True},
        )

        self.assertIn('"ok": true', result)
        self.assertIn('"name": "svc"', result)

    def test_format_path_quotes_path_params(self) -> None:
        self.assertEqual(_format_path("/services/{name}", {"name": "a/b"}), "/services/a%2Fb")
