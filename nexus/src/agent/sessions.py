"""Session storage for the Agent API."""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Protocol

import asyncpg

from src.agent.config import CHAT_DB_ENABLED, chat_db_config
from src.agent.models import ChatMessage, ChatSession, ChatToolCall

logger = logging.getLogger(__name__)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def now() -> float:
    return time.time()


class SessionStore(Protocol):
    async def create(self, title: str | None = None) -> ChatSession:
        ...

    async def get(self, session_id: str) -> ChatSession | None:
        ...

    async def add_user_message(self, session: ChatSession, content: str) -> ChatMessage:
        ...

    async def add_assistant_message(
        self,
        session: ChatSession,
        content: str,
        tool_calls: list[ChatToolCall],
    ) -> ChatMessage:
        ...


class InMemorySessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, ChatSession] = {}

    async def create(self, title: str | None = None) -> ChatSession:
        timestamp = now()
        session = ChatSession(
            id=new_id("chat"),
            title=title or "排障会话",
            created_at=timestamp,
            updated_at=timestamp,
        )
        self._sessions[session.id] = session
        return session

    async def get(self, session_id: str) -> ChatSession | None:
        return self._sessions.get(session_id)

    async def add_user_message(self, session: ChatSession, content: str) -> ChatMessage:
        message = ChatMessage(
            id=new_id("msg"),
            role="user",
            content=content,
            created_at=now(),
        )
        session.messages.append(message)
        session.updated_at = message.created_at
        return message

    async def add_assistant_message(
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


class PostgresSessionStore:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def create(self, title: str | None = None) -> ChatSession:
        timestamp = now()
        session = ChatSession(
            id=new_id("chat"),
            title=title or "排障会话",
            created_at=timestamp,
            updated_at=timestamp,
        )
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO chat_session (id, title, created_at, updated_at)
                VALUES ($1, $2, $3, $4)
                """,
                session.id,
                session.title,
                session.created_at,
                session.updated_at,
            )
        return session

    async def get(self, session_id: str) -> ChatSession | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, title, created_at, updated_at
                FROM chat_session
                WHERE id = $1
                """,
                session_id,
            )
            if not row:
                return None
            message_rows = await conn.fetch(
                """
                SELECT id, role, content, created_at, tool_calls
                FROM chat_message
                WHERE session_id = $1
                ORDER BY created_at ASC, id ASC
                """,
                session_id,
            )

        return ChatSession(
            id=row["id"],
            title=row["title"],
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
            messages=[_row_to_message(message_row) for message_row in message_rows],
        )

    async def add_user_message(self, session: ChatSession, content: str) -> ChatMessage:
        message = ChatMessage(
            id=new_id("msg"),
            role="user",
            content=content,
            created_at=now(),
        )
        await self._insert_message(session, message)
        return message

    async def add_assistant_message(
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
        await self._insert_message(session, message)
        return message

    async def _insert_message(self, session: ChatSession, message: ChatMessage) -> None:
        payload = json.dumps(
            [call.model_dump(mode="json") for call in message.tool_calls],
            ensure_ascii=False,
            default=str,
        )
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO chat_message (id, session_id, role, content, created_at, tool_calls)
                    VALUES ($1, $2, $3, $4, $5, $6::jsonb)
                    """,
                    message.id,
                    session.id,
                    message.role,
                    message.content,
                    message.created_at,
                    payload,
                )
                await conn.execute(
                    """
                    UPDATE chat_session
                    SET updated_at = $2
                    WHERE id = $1
                    """,
                    session.id,
                    message.created_at,
                )
        session.messages.append(message)
        session.updated_at = message.created_at


class HybridSessionStore:
    """PG 优先，会话库不可用时降级为内存存储。"""

    def __init__(self) -> None:
        self._memory = InMemorySessionStore()
        self._pool: asyncpg.Pool | None = None
        self._pg: PostgresSessionStore | None = None

    async def init(self) -> None:
        if not CHAT_DB_ENABLED:
            logger.info("Agent Chat PG 持久化已禁用，使用内存会话")
            return

        cfg = chat_db_config()
        try:
            self._pool = await asyncpg.create_pool(
                host=str(cfg["host"]),
                port=int(cfg["port"]),
                user=str(cfg["user"]),
                password=str(cfg["password"]),
                database=str(cfg["database"]),
                min_size=1,
                max_size=5,
            )
            await _ensure_tables(self._pool)
            self._pg = PostgresSessionStore(self._pool)
            logger.info(
                "Agent Chat PostgreSQL 持久化已启用: %s:%s/%s",
                cfg["host"],
                cfg["port"],
                cfg["database"],
            )
        except Exception:
            logger.warning("Agent Chat 无法连接 PostgreSQL，将使用内存会话", exc_info=True)
            self._pool = None
            self._pg = None

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()
            self._pool = None
            self._pg = None

    @property
    def _active(self) -> SessionStore:
        return self._pg or self._memory

    async def create(self, title: str | None = None) -> ChatSession:
        return await self._active.create(title)

    async def get(self, session_id: str) -> ChatSession | None:
        return await self._active.get(session_id)

    async def add_user_message(self, session: ChatSession, content: str) -> ChatMessage:
        return await self._active.add_user_message(session, content)

    async def add_assistant_message(
        self,
        session: ChatSession,
        content: str,
        tool_calls: list[ChatToolCall],
    ) -> ChatMessage:
        return await self._active.add_assistant_message(session, content, tool_calls)


async def _ensure_tables(pool: asyncpg.Pool) -> None:
    ddl = """
    CREATE TABLE IF NOT EXISTS chat_session (
        id         VARCHAR(64) PRIMARY KEY,
        title      TEXT             NOT NULL DEFAULT '',
        created_at DOUBLE PRECISION NOT NULL,
        updated_at DOUBLE PRECISION NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_chat_session_updated
        ON chat_session (updated_at DESC);

    CREATE TABLE IF NOT EXISTS chat_message (
        id         VARCHAR(64) PRIMARY KEY,
        session_id VARCHAR(64)      NOT NULL REFERENCES chat_session(id) ON DELETE CASCADE,
        role       VARCHAR(16)      NOT NULL,
        content    TEXT             NOT NULL DEFAULT '',
        created_at DOUBLE PRECISION NOT NULL,
        tool_calls JSONB            NOT NULL DEFAULT '[]'
    );
    CREATE INDEX IF NOT EXISTS idx_chat_message_session_time
        ON chat_message (session_id, created_at ASC);
    """
    async with pool.acquire() as conn:
        await conn.execute(ddl)


def _row_to_message(row) -> ChatMessage:
    tool_calls = row["tool_calls"]
    if isinstance(tool_calls, str):
        tool_calls = json.loads(tool_calls)
    return ChatMessage(
        id=row["id"],
        role=row["role"],
        content=row["content"],
        created_at=float(row["created_at"]),
        tool_calls=[ChatToolCall(**call) for call in (tool_calls or [])],
    )
