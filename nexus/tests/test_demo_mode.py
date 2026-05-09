from __future__ import annotations

import os
import unittest
from unittest import mock

from httpx import ASGITransport, AsyncClient

from src.server import create_app


class NexusDemoModeTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.env = mock.patch.dict(os.environ, {}, clear=False)
        self.env.start()
        os.environ["NEXUS_DEMO_MODE"] = "true"
        os.environ.pop("NEXUS_AUTH_ENABLED", None)
        os.environ.pop("NEXUS_AUTH_USERNAME", None)
        os.environ.pop("NEXUS_AUTH_PASSWORD", None)

    async def asyncTearDown(self) -> None:
        self.env.stop()

    async def test_demo_mode_exposes_only_demo_safe_routes(self) -> None:
        app = create_app()
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
            follow_redirects=False,
        ) as client:
            info = await client.get("/api/nexus")
            self.assertEqual(info.status_code, 200)
            self.assertTrue(info.json()["demo"]["enabled"])

            blocked_api = await client.get("/api/atlas/services")
            self.assertEqual(blocked_api.status_code, 403)
            self.assertEqual(blocked_api.json()["error"], "demo_restricted")

            blocked_frontend = await client.get("/atlas")
            self.assertEqual(blocked_frontend.status_code, 303)
            self.assertEqual(blocked_frontend.headers["location"], "/")

            chat_list = await client.get("/api/chat/sessions")
            self.assertEqual(chat_list.status_code, 403)

            created = await client.post("/api/chat/sessions", json={"title": "demo"})
            self.assertEqual(created.status_code, 200)
