"""FastAPI routes for Meridian Agent Chat."""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from src.agent.config import AGENT_TURN_TIMEOUT_SECONDS, get_chat_config
from src.agent.models import (
    ChatConfig,
    ChatMessageSearchHit,
    ChatMessageSearchResponse,
    ChatSession,
    ChatSessionListResponse,
    ChatTurnResponse,
    CreateSessionRequest,
    ModelProviderError,
    SendMessageRequest,
    ToolExecutor,
)
from src.agent.providers import LangChainModelAdapter
from src.agent.runtime import AgentRuntime
from src.agent.sessions import InMemorySessionStore, SessionStore

logger = logging.getLogger(__name__)
CHAT_EVENT_POLL_SECONDS = 0.5
CHAT_EVENT_HEARTBEAT_SECONDS = 15


class SessionTurnLocks:
    """Best-effort in-process guard for one active Agent turn per chat session."""

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}
        self._guard = asyncio.Lock()

    async def try_acquire(self, session_id: str) -> asyncio.Lock | None:
        async with self._guard:
            lock = self._locks.get(session_id)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[session_id] = lock
            if lock.locked():
                return None
            await lock.acquire()
            return lock

    async def release(self, session_id: str, lock: asyncio.Lock) -> None:
        lock.release()
        async with self._guard:
            if self._locks.get(session_id) is lock and not lock.locked():
                self._locks.pop(session_id, None)


def _sse_event(event: str, data: dict) -> str:
    payload = json.dumps(data, ensure_ascii=False, default=str)
    return f"event: {event}\ndata: {payload}\n\n"


def create_chat_router(tool_executor: ToolExecutor, session_store: SessionStore | None = None) -> APIRouter:
    router = APIRouter()
    sessions = session_store or InMemorySessionStore()
    turn_locks = SessionTurnLocks()

    @router.get("/config", response_model=ChatConfig)
    async def config() -> ChatConfig:
        return get_chat_config()

    @router.post("/sessions", response_model=ChatSession)
    async def create_session(request: CreateSessionRequest | None = None) -> ChatSession:
        return await sessions.create(request.title if request else None)

    @router.get("/sessions", response_model=ChatSessionListResponse)
    async def list_sessions(limit: int = 20) -> ChatSessionListResponse:
        return ChatSessionListResponse(sessions=await sessions.list_recent(limit))

    @router.get("/messages/search", response_model=ChatMessageSearchResponse)
    async def search_messages(q: str, limit: int = 20) -> ChatMessageSearchResponse:
        query = q.strip()
        if not query:
            raise HTTPException(status_code=400, detail="Search query is required")
        matches = await sessions.search_messages(query, limit)
        return ChatMessageSearchResponse(
            query=query,
            matches=[
                ChatMessageSearchHit(
                    session_id=session.id,
                    session_title=session.title,
                    message=message,
                )
                for session, message in matches
            ],
        )

    @router.get("/sessions/{session_id}", response_model=ChatSession)
    async def get_session(session_id: str) -> ChatSession:
        session = await sessions.get(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Chat session not found")
        return session

    @router.get("/sessions/{session_id}/events")
    async def session_events(
        session_id: str,
        request: Request,
        after: int = Query(0, ge=0),
        timeout_seconds: int = Query(120, ge=1, le=300),
    ) -> StreamingResponse:
        session = await sessions.get(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Chat session not found")

        async def event_stream():
            deadline = asyncio.get_running_loop().time() + timeout_seconds
            next_heartbeat = asyncio.get_running_loop().time() + CHAT_EVENT_HEARTBEAT_SECONDS
            while asyncio.get_running_loop().time() < deadline:
                if await request.is_disconnected():
                    return

                current = await sessions.get(session_id)
                if not current:
                    yield _sse_event("error", {"detail": "Chat session not found"})
                    return

                new_messages = current.messages[after:]
                if any(message.role == "assistant" for message in new_messages):
                    yield _sse_event("session", current.model_dump(mode="json"))
                    return

                now = asyncio.get_running_loop().time()
                if now >= next_heartbeat:
                    yield _sse_event("ping", {"session_id": session_id})
                    next_heartbeat = now + CHAT_EVENT_HEARTBEAT_SECONDS
                await asyncio.sleep(CHAT_EVENT_POLL_SECONDS)

            latest = await sessions.get(session_id)
            yield _sse_event(
                "timeout",
                latest.model_dump(mode="json") if latest else {"session_id": session_id},
            )

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    @router.post("/sessions/{session_id}/messages", response_model=ChatTurnResponse)
    async def send_message(session_id: str, request: SendMessageRequest) -> ChatTurnResponse:
        session = await sessions.get(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Chat session not found")

        content = request.content.strip()
        if not content:
            raise HTTPException(status_code=400, detail="Message content is required")

        turn_lock = await turn_locks.try_acquire(session_id)
        if turn_lock is None:
            raise HTTPException(
                status_code=409,
                detail="该会话上一条消息仍在处理中，请等待完成后再发送。",
            )

        try:
            await sessions.add_user_message(session, content)

            adapter = LangChainModelAdapter()
            runtime = AgentRuntime(adapter, tool_executor)
            try:
                text, tool_calls = await asyncio.wait_for(
                    runtime.run(session.messages),
                    timeout=AGENT_TURN_TIMEOUT_SECONDS,
                )
            except TimeoutError:
                detail = (
                    f"Agent 响应超时（{AGENT_TURN_TIMEOUT_SECONDS}s）。"
                    "这次消息已记录，但模型或工具链路没有在限制时间内返回可用结果。"
                    "请稍后重试，或补充更精确的时间范围后重新查询。"
                )
                logger.warning(
                    "Agent turn timed out after %s seconds: session=%s provider=%s model=%s",
                    AGENT_TURN_TIMEOUT_SECONDS,
                    session_id,
                    adapter.config.provider,
                    adapter.config.model,
                )
                assistant = await sessions.add_assistant_message(session, detail, [])
                return ChatTurnResponse(
                    session_id=session.id,
                    provider=adapter.config.provider,
                    model=adapter.config.model,
                    assistant=assistant,
                    tool_calls=[],
                    session=session,
                )
            except ModelProviderError as exc:
                detail = (
                    f"模型调用失败：{exc}。"
                    "这次消息已记录，请检查模型网关/API Key/网络连通性后重试。"
                )
                assistant = await sessions.add_assistant_message(session, detail, [])
                return ChatTurnResponse(
                    session_id=session.id,
                    provider=adapter.config.provider,
                    model=adapter.config.model,
                    assistant=assistant,
                    tool_calls=[],
                    session=session,
                )

            assistant = await sessions.add_assistant_message(
                session,
                text or "我没有得到可用的模型输出。",
                tool_calls,
            )

            return ChatTurnResponse(
                session_id=session.id,
                provider=adapter.config.provider,
                model=adapter.config.model,
                assistant=assistant,
                tool_calls=tool_calls,
                session=session,
            )
        finally:
            await turn_locks.release(session_id, turn_lock)

    return router
