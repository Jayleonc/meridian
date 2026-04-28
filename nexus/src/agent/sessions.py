"""Session storage for the Agent API.

This is intentionally in-memory for the MVP.  The API layer depends on this
small interface so it can be replaced by PostgreSQL without touching Console.
"""

from __future__ import annotations

import time
import uuid

from src.agent.models import ChatMessage, ChatSession, ChatToolCall


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def now() -> float:
    return time.time()


class InMemorySessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, ChatSession] = {}

    def create(self, title: str | None = None) -> ChatSession:
        timestamp = now()
        session = ChatSession(
            id=new_id("chat"),
            title=title or "Investigation",
            created_at=timestamp,
            updated_at=timestamp,
        )
        self._sessions[session.id] = session
        return session

    def get(self, session_id: str) -> ChatSession | None:
        return self._sessions.get(session_id)

    def add_user_message(self, session: ChatSession, content: str) -> ChatMessage:
        message = ChatMessage(
            id=new_id("msg"),
            role="user",
            content=content,
            created_at=now(),
        )
        session.messages.append(message)
        session.updated_at = message.created_at
        return message

    def add_assistant_message(
        self,
        session: ChatSession,
        content: str,
        tool_calls: list[ChatToolCall],
    ) -> ChatMessage:
        message = ChatMessage(
            id=new_id("msg"),
            role="assistant",
            content=content,
            created_at=now(),
            tool_calls=tool_calls,
        )
        session.messages.append(message)
        session.updated_at = message.created_at
        return message
