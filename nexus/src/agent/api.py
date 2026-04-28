"""FastAPI routes for Meridian Agent Chat."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from src.agent.config import get_chat_config
from src.agent.models import (
    ChatConfig,
    ChatSession,
    ChatTurnResponse,
    CreateSessionRequest,
    ModelProviderError,
    SendMessageRequest,
    ToolExecutor,
)
from src.agent.providers import LangChainModelAdapter
from src.agent.runtime import AgentRuntime
from src.agent.sessions import InMemorySessionStore


def create_chat_router(tool_executor: ToolExecutor) -> APIRouter:
    router = APIRouter()
    sessions = InMemorySessionStore()

    @router.get("/config", response_model=ChatConfig)
    async def config() -> ChatConfig:
        return get_chat_config()

    @router.post("/sessions", response_model=ChatSession)
    async def create_session(request: CreateSessionRequest | None = None) -> ChatSession:
        return sessions.create(request.title if request else None)

    @router.get("/sessions/{session_id}", response_model=ChatSession)
    async def get_session(session_id: str) -> ChatSession:
        session = sessions.get(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Chat session not found")
        return session

    @router.post("/sessions/{session_id}/messages", response_model=ChatTurnResponse)
    async def send_message(session_id: str, request: SendMessageRequest) -> ChatTurnResponse:
        session = sessions.get(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Chat session not found")

        content = request.content.strip()
        if not content:
            raise HTTPException(status_code=400, detail="Message content is required")

        sessions.add_user_message(session, content)

        adapter = LangChainModelAdapter()
        runtime = AgentRuntime(adapter, tool_executor)
        try:
            text, tool_calls = await runtime.run(session.messages)
        except ModelProviderError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        assistant = sessions.add_assistant_message(
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
