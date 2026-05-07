from __future__ import annotations

import unittest

from pydantic import ValidationError

import src.server as server
from src.agent.tools import tool_schemas, validate_tool_args


class AgentToolSchemaTest(unittest.TestCase):
    def test_atlas_and_lens_tools_are_exposed_to_chat_runtime(self) -> None:
        names = {schema["function"]["name"] for schema in tool_schemas()}

        self.assertIn("atlas_list_services", names)
        self.assertIn("atlas_search_meta", names)
        self.assertIn("atlas_get_table", names)
        self.assertIn("lens_list_entities", names)
        self.assertIn("lens_describe_entity", names)
        self.assertIn("lens_query", names)
        self.assertIn("meridian_diagnose_request", names)
        self.assertIn("probe_search_ops_logs", names)

    def test_meridian_diagnose_request_args(self) -> None:
        args = validate_tool_args(
            "meridian_diagnose_request",
            {
                "request_id": "rid-1",
                "back_hours": 2,
                "include_lens_counts": True,
                "max_entities": 2,
            },
        )

        self.assertEqual(args["request_id"], "rid-1")
        self.assertEqual(args["back_hours"], 2)
        self.assertEqual(args["max_entities"], 2)

    def test_lens_query_accepts_count_and_rejects_unknown_aggregate(self) -> None:
        args = validate_tool_args(
            "lens_query",
            {
                "entity": "order",
                "filter": [{"field": "status", "op": "eq", "value": "paid"}],
                "aggregate": "count",
                "limit": 1,
            },
        )

        self.assertEqual(args["aggregate"], "count")
        self.assertEqual(args["filter"][0]["field"], "status")

        with self.assertRaises(ValidationError):
            validate_tool_args("lens_query", {"entity": "order", "aggregate": "sum"})


class ChatToolDispatchTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.original_request_service = server._request_service
        self.calls: list[dict] = []

        async def fake_request_service(
            service: str,
            method: str,
            path: str,
            *,
            params: dict | None = None,
            json_body: dict | None = None,
        ) -> dict:
            self.calls.append(
                {
                    "service": service,
                    "method": method,
                    "path": path,
                    "params": params,
                    "json_body": json_body,
                }
            )
            if service == "atlas" and path == "/api/services":
                return {
                    "count": 2,
                    "service": [
                        {"name": "order-service", "status": "RUNNING"},
                        {"name": "payment-service", "status": "RUNNING"},
                    ],
                }
            if service == "atlas" and path == "/api/schemas/search/meta":
                query = params["q"] if params else ""
                return {
                    "query": query,
                    "matched_table": [{"database": "test", "name": "order"}] if "order" in query else [],
                    "matched_column": [],
                }
            if service == "probe" and path.startswith("/api/logs/trace/"):
                return {
                    "request_id": "rid-1",
                    "total_lines": 3,
                    "time_range": "04-30T10:00:00 ~ 04-30T10:00:02",
                    "searched_hours": params.get("back_hours", 0) if params else 0,
                    "services": ["order-service", "payment-service"],
                    "error_count": 1,
                    "warn_count": 0,
                    "errors": [
                        {
                            "timestamp": "04-30T10:00:02",
                            "level": "ERR",
                            "service": "order-service",
                            "source": "order.go:1",
                            "message": "order payment failed",
                            "request_id": "rid-1",
                        }
                    ],
                    "warns": [],
                    "timeline": [],
                    "service_stats": {
                        "order-service": {
                            "total": 2,
                            "error": 1,
                            "warn": 0,
                            "first_seen": "04-30T10:00:00",
                            "last_seen": "04-30T10:00:02",
                        }
                    },
                    "suspects": [
                        {
                            "timestamp": "04-30T10:00:02",
                            "level": "ERR",
                            "service": "order-service",
                            "message": "order payment failed",
                            "reason": "ERR 日志表示失败分支",
                        }
                    ],
                    "hint": "",
                    "next_actions": [],
                }
            if service == "lens" and path == "/api/entities":
                return {
                    "count": 2,
                    "entity": [
                        {"name": "order", "display_name": "订单", "database": "test", "db_type": "mysql"},
                        {"name": "customer", "display_name": "客户", "database": "test", "db_type": "mysql"},
                    ],
                }
            if service == "lens" and path == "/api/entities/order":
                return {
                    "name": "order",
                    "display_name": "订单",
                    "database": "test",
                    "primary_table": "order",
                    "fields": {
                        "id": {"type": "bigint", "semantic": "订单ID", "filterable": True, "sortable": True},
                        "status": {"type": "varchar", "semantic": "订单状态", "filterable": True, "sortable": True},
                    },
                    "constraint": {},
                }
            if service == "lens" and path == "/api/entities/query":
                return {"success": True, "count": 42, "data": [], "duration_ms": 3}
            if service == "probe" and path == "/api/logs/ops/search":
                return {
                    "query": json_body,
                    "summary": {"status": "unavailable", "available": False},
                    "items": [],
                }
            return {"ok": True}

        server._request_service = fake_request_service

    async def asyncTearDown(self) -> None:
        server._request_service = self.original_request_service

    async def test_atlas_tools_route_to_atlas_api(self) -> None:
        await server._call_chat_tool("atlas_list_services", {})
        search_result = await server._call_chat_tool("atlas_search_meta", {"query": "order"})
        await server._call_chat_tool("atlas_get_table", {"database": "test", "table": "order"})

        self.assertEqual(search_result["matched_service"][0]["name"], "order-service")
        self.assertEqual(
            self.calls,
            [
                {
                    "service": "atlas",
                    "method": "GET",
                    "path": "/api/services",
                    "params": None,
                    "json_body": None,
                },
                {
                    "service": "atlas",
                    "method": "GET",
                    "path": "/api/schemas/search/meta",
                    "params": {"q": "order"},
                    "json_body": None,
                },
                {
                    "service": "atlas",
                    "method": "GET",
                    "path": "/api/services",
                    "params": None,
                    "json_body": None,
                },
                {
                    "service": "atlas",
                    "method": "GET",
                    "path": "/api/schemas/test/tables/order",
                    "params": None,
                    "json_body": None,
                },
            ],
        )

    async def test_lens_tools_route_to_lens_api(self) -> None:
        dsl = {
            "entity": "order",
            "filter": [{"field": "status", "op": "eq", "value": "paid"}],
            "aggregate": "count",
            "limit": 1,
        }

        await server._call_chat_tool("lens_list_entities", {})
        await server._call_chat_tool("lens_describe_entity", {"entity": "order"})
        await server._call_chat_tool("lens_query", dsl)

        self.assertEqual(
            self.calls,
            [
                {
                    "service": "lens",
                    "method": "GET",
                    "path": "/api/entities",
                    "params": None,
                    "json_body": None,
                },
                {
                    "service": "lens",
                    "method": "GET",
                    "path": "/api/entities/order",
                    "params": None,
                    "json_body": None,
                },
                {
                    "service": "lens",
                    "method": "POST",
                    "path": "/api/entities/query",
                    "params": None,
                    "json_body": dsl,
                },
            ],
        )

    async def test_meridian_diagnose_request_collects_probe_atlas_lens_evidence(self) -> None:
        result = await server._call_chat_tool(
            "meridian_diagnose_request",
            {
                "request_id": "rid-1",
                "back_hours": 2,
                "include_lens_counts": True,
                "max_entities": 1,
            },
        )

        self.assertEqual(result["request_id"], "rid-1")
        self.assertEqual(result["trace"]["error_count"], 1)
        self.assertIn("order", result["terms"])
        self.assertGreaterEqual(len(result["atlas_queries"]), 1)
        self.assertEqual(result["lens_candidates"][0]["summary"]["name"], "order")
        self.assertEqual(result["lens_candidates"][0]["count"]["count"], 42)

    async def test_probe_ops_tool_routes_to_probe_ops_api(self) -> None:
        result = await server._call_chat_tool(
            "probe_search_ops_logs",
            {
                "service": "jzadapter",
                "keyword": "timeout",
                "hosts": ["app-01"],
                "hours_back": 1,
                "limit": 20,
            },
        )

        self.assertEqual(result["summary"]["status"], "unavailable")
        self.assertEqual(
            self.calls[-1],
            {
                "service": "probe",
                "method": "POST",
                "path": "/api/logs/ops/search",
                "params": None,
                "json_body": {
                    "service": "jzadapter",
                    "keyword": "timeout",
                    "hosts": ["app-01"],
                    "hours_back": 1,
                    "limit": 20,
                },
            },
        )

    def test_registry_lists_agent_relevant_atlas_and_lens_tools(self) -> None:
        self.assertEqual(
            server._registry["atlas"]["tools"],
            ["atlas.health.v1", "atlas.list_services", "atlas.search_meta", "atlas.get_table"],
        )
        self.assertIn("probe.search_ops_logs", server._registry["probe"]["tools"])
        self.assertEqual(
            server._registry["lens"]["tools"],
            ["lens.list_entities", "lens.describe_entity", "lens.query"],
        )

    def test_registry_declares_controlled_tool_exposure_policy(self) -> None:
        payload = server._registry_payload()

        self.assertEqual(payload["tool_exposure"]["mode"], "controlled_gateway")
        self.assertFalse(payload["tool_exposure"]["transparent_downstream_mcp"])
        self.assertEqual(payload["tool_exposure"]["source"], "nexus_registry_allowlist")
        self.assertEqual(
            payload["service"][0]["tool_exposure"],
            {
                "source": "nexus_registry_allowlist",
                "transparent_downstream_mcp": False,
            },
        )

    def test_registry_loads_tool_manifests(self) -> None:
        atlas_tools = {
            tool["name"]: tool
            for tool in server._registry["atlas"]["tool_manifests"]
        }

        self.assertEqual(atlas_tools["atlas.list_services"]["adapter"], "http")
        self.assertEqual(atlas_tools["atlas.list_services"]["chat_name"], "atlas_list_services")
        self.assertEqual(atlas_tools["atlas.list_services"]["path"], "/api/services")
        self.assertEqual(atlas_tools["atlas.health.v1"]["status"], "approved")

    def test_server_registers_manifest_only_mcp_tools(self) -> None:
        self.assertIn("atlas.health.v1", server._dynamic_tools_registered)
        self.assertIsNotNone(server.mcp._tool_manager.get_tool("atlas.health.v1"))
