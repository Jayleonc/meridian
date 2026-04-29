"""Public API models for the Meridian Agent runtime."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Literal

from pydantic import BaseModel, Field

ToolExecutor = Callable[[str, dict[str, Any]], Awaitable[Any]]


class ChatToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    result: Any = None
    error: str | None = None
    duration_ms: int = 0


class ChatMessage(BaseModel):
    id: str
    role: Literal["user", "assistant"]
    content: str
    created_at: float
    tool_calls: list[ChatToolCall] = Field(default_factory=list)


class ChatSession(BaseModel):
    id: str
    title: str
    created_at: float
    updated_at: float
    messages: list[ChatMessage] = Field(default_factory=list)


class ChatSessionSummary(BaseModel):
    id: str
    title: str
    created_at: float
    updated_at: float
    message_count: int = 0
    last_message_role: str | None = None
    last_message_preview: str = ""


class ChatSessionListResponse(BaseModel):
    sessions: list[ChatSessionSummary]


class ChatMessageSearchHit(BaseModel):
    session_id: str
    session_title: str
    message: ChatMessage


class ChatMessageSearchResponse(BaseModel):
    query: str
    matches: list[ChatMessageSearchHit]


class CreateSessionRequest(BaseModel):
    title: str | None = None


class SendMessageRequest(BaseModel):
    content: str = Field(..., min_length=1)


class ChatConfig(BaseModel):
    provider: str
    model: str
    configured: bool
    base_url: str | None = None
    max_tool_rounds: int
    tools: list[str]


class ChatTurnResponse(BaseModel):
    session_id: str
    provider: str
    model: str
    assistant: ChatMessage
    tool_calls: list[ChatToolCall]
    session: ChatSession


class ModelProviderError(RuntimeError):
    pass
