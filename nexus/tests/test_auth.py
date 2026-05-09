from __future__ import annotations

import os
import unittest
from unittest import mock

from httpx import ASGITransport, AsyncClient

from src.server import create_app


AUTH_ENV_KEYS = (
    "NEXUS_AUTH_ENABLED",
    "NEXUS_AUTH_USERNAME",
    "NEXUS_AUTH_PASSWORD",
    "NEXUS_AUTH_SECRET",
    "NEXUS_AUTH_SESSION_SECONDS",
    "NEXUS_AUTH_COOKIE_SECURE",
)


class NexusAuthTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.env = mock.patch.dict(os.environ, {}, clear=False)
        self.env.start()
        for key in AUTH_ENV_KEYS:
            os.environ.pop(key, None)

    async def asyncTearDown(self) -> None:
        self.env.stop()

    async def test_auth_is_disabled_by_default(self) -> None:
        app = create_app()
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
            follow_redirects=False,
        ) as client:
            response = await client.get("/api/nexus")
            self.assertEqual(response.status_code, 200)

            me = await client.get("/api/auth/me")
            self.assertEqual(me.status_code, 200)
            self.assertFalse(me.json()["enabled"])

    async def test_auth_gate_requires_login_and_accepts_session_cookie(self) -> None:
        os.environ.update(
            {
                "NEXUS_AUTH_ENABLED": "true",
                "NEXUS_AUTH_USERNAME": "demo",
                "NEXUS_AUTH_PASSWORD": "secret",
                "NEXUS_AUTH_SECRET": "test-secret",
            }
        )
        app = create_app()

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
            follow_redirects=False,
        ) as client:
            api_denied = await client.get("/api/nexus")
            self.assertEqual(api_denied.status_code, 401)

            page_denied = await client.get("/")
            self.assertEqual(page_denied.status_code, 303)
            self.assertTrue(page_denied.headers["location"].startswith("/login?next="))

            bad_login = await client.post(
                "/api/auth/login",
                json={"username": "demo", "password": "wrong"},
            )
            self.assertEqual(bad_login.status_code, 401)

            login = await client.post(
                "/api/auth/login",
                json={"username": "demo", "password": "secret"},
            )
            self.assertEqual(login.status_code, 200)
            self.assertIn("meridian_session", login.headers["set-cookie"])

            allowed = await client.get("/api/nexus")
            self.assertEqual(allowed.status_code, 200)
            self.assertTrue(allowed.json()["auth"]["enabled"])

            logout = await client.post("/api/auth/logout")
            self.assertEqual(logout.status_code, 200)

            denied_again = await client.get("/api/nexus")
            self.assertEqual(denied_again.status_code, 401)

    async def test_enabled_auth_without_credentials_fails_closed(self) -> None:
        os.environ["NEXUS_AUTH_ENABLED"] = "true"
        app = create_app()

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
            follow_redirects=False,
        ) as client:
            response = await client.get("/api/nexus")
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json()["error"], "auth_not_configured")
