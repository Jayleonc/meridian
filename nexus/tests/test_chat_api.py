from __future__ import annotations

import asyncio
import contextlib
import unittest

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import src.agent.api as chat_api
from src.agent.api import create_chat_router


class FakeConfig:
    provider = "test"
    model = "fake"


class FakeAdapter:
    def __init__(self) -> None:
        self.config = FakeConfig()


async def fake_tool_executor(name: str, arguments: dict) -> dict:
    return {"name": name, "arguments": arguments}


class ChatApiConcurrencyTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.original_runtime = chat_api.AgentRuntime
        self.original_adapter = chat_api.LangChainModelAdapter
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.runtime_calls = 0

        test_case = self

        class SlowRuntime:
            def __init__(self, adapter, tool_executor) -> None:
                self.adapter = adapter
                self.tool_executor = tool_executor

            async def run(self, messages):
                test_case.runtime_calls += 1
                test_case.started.set()
                await test_case.release.wait()
                return "ok", []

        chat_api.AgentRuntime = SlowRuntime
        chat_api.LangChainModelAdapter = FakeAdapter

        app = FastAPI()
        app.include_router(create_chat_router(fake_tool_executor), prefix="/api/chat")
        transport = ASGITransport(app=app)
        self.client = AsyncClient(transport=transport, base_url="http://testserver")

    async def asyncTearDown(self) -> None:
        self.release.set()
        await self.client.aclose()
        chat_api.AgentRuntime = self.original_runtime
        chat_api.LangChainModelAdapter = self.original_adapter

    async def test_concurrent_turn_is_rejected_before_duplicate_user_message(self) -> None:
        created = await self.client.post("/api/chat/sessions", json={"title": "test"})
        self.assertEqual(created.status_code, 200)
        session_id = created.json()["id"]

        first = asyncio.create_task(
            self.client.post(
                f"/api/chat/sessions/{session_id}/messages",
                json={"content": "same question"},
            )
        )
        try:
            await asyncio.wait_for(self.started.wait(), timeout=1)

            second = await self.client.post(
                f"/api/chat/sessions/{session_id}/messages",
                json={"content": "same question"},
            )
            self.assertEqual(second.status_code, 409)

            during_turn = await self.client.get(f"/api/chat/sessions/{session_id}")
            self.assertEqual(during_turn.status_code, 200)
            self.assertEqual(
                [message["role"] for message in during_turn.json()["messages"]],
                ["user"],
            )

            self.release.set()
            completed = await first
        finally:
            if not first.done():
                first.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await first

        self.assertEqual(completed.status_code, 200)
        self.assertEqual(self.runtime_calls, 1)
        messages = completed.json()["session"]["messages"]
        self.assertEqual([message["role"] for message in messages], ["user", "assistant"])
        self.assertEqual(messages[0]["content"], "same question")
