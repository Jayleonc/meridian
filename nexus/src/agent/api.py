"""FastAPI routes for Meridian Agent Chat."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException

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


def create_chat_router(tool_executor: ToolExecutor, session_store: SessionStore | None = None) -> APIRouter:
    router = APIRouter()
    sessions = session_store or InMemorySessionStore()

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

    @router.post("/sessions/{session_id}/messages", response_model=ChatTurnResponse)
    async def send_message(session_id: str, request: SendMessageRequest) -> ChatTurnResponse:
        session = await sessions.get(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Chat session not found")

        content = request.content.strip()
        if not content:
            raise HTTPException(status_code=400, detail="Message content is required")

        await sessions.add_user_message(session, content)

        adapter = LangChainModelAdapter()
        runtime = AgentRuntime(adapter, tool_executor)
        try:
            text, tool_calls = await asyncio.wait_for(
                runtime.run(session.messages),
                timeout=AGENT_TURN_TIMEOUT_SECONDS,
            )
        except TimeoutError as exc:
            logger.warning(
                "Agent turn timed out after %s seconds: session=%s provider=%s model=%s",
                AGENT_TURN_TIMEOUT_SECONDS,
                session_id,
                adapter.config.provider,
                adapter.config.model,
            )
            raise HTTPException(
                status_code=504,
                detail=(
                    f"Agent 响应超时（{AGENT_TURN_TIMEOUT_SECONDS}s）。"
                    "请检查模型网关/API Key/网络连通性，或缩小问题范围后重试。"
                ),
            ) from exc
        except ModelProviderError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

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

    return router
