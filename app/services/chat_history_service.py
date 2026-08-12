import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from app.core.database import db_connection


MessageRole = Literal["user", "assistant", "system", "tool"]


@dataclass(slots=True)
class ChatSessionRecord:
    id: uuid.UUID
    user_id: uuid.UUID
    thread_id: str
    title: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True)
class ChatMessageRecord:
    id: int
    session_id: uuid.UUID
    role: MessageRole
    content: str
    created_at: datetime
    tool_calls: list[dict] = field(default_factory=list)


def _make_title(message: str) -> str:
    compact = " ".join(message.split())
    return compact[:80] or "新会话"


def _row_to_session(row) -> ChatSessionRecord:
    return ChatSessionRecord(
        id=row["id"],
        user_id=row["user_id"],
        thread_id=row["thread_id"],
        title=row["title"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_message(row) -> ChatMessageRecord:
    return ChatMessageRecord(
        id=row["id"],
        session_id=row["session_id"],
        role=row["role"],
        content=row["content"],
        tool_calls=row["tool_calls"] or [],
        created_at=row["created_at"],
    )


async def _ensure_chat_session(
    conn,
    *,
    user_id: uuid.UUID,
    thread_id: str,
    title: str | None = None,
) -> ChatSessionRecord:
    session_id = uuid.uuid4()
    cur = await conn.execute(
        """
        INSERT INTO chat_sessions (id, user_id, thread_id, title)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (user_id, thread_id) DO UPDATE SET
            title = COALESCE(chat_sessions.title, EXCLUDED.title),
            updated_at = now()
        RETURNING id, user_id, thread_id, title, created_at, updated_at
        """,
        (session_id, user_id, thread_id, title),
    )
    row = await cur.fetchone()

    return _row_to_session(row)


async def ensure_chat_session(
    *,
    user_id: uuid.UUID,
    thread_id: str,
    title: str | None = None,
) -> ChatSessionRecord:
    async with db_connection() as conn:
        return await _ensure_chat_session(
            conn,
            user_id=user_id,
            thread_id=thread_id,
            title=title,
        )


async def record_chat_exchange(
    *,
    user_id: uuid.UUID,
    thread_id: str,
    user_message: str,
    assistant_reply: str,
    tool_calls: list[dict],
) -> ChatSessionRecord:
    from psycopg.types.json import Jsonb

    async with db_connection() as conn:
        async with conn.transaction():
            session = await _ensure_chat_session(
                conn,
                user_id=user_id,
                thread_id=thread_id,
                title=_make_title(user_message),
            )
            await conn.execute(
                """
                INSERT INTO chat_messages (session_id, role, content)
                VALUES (%s, 'user', %s)
                """,
                (session.id, user_message),
            )
            await conn.execute(
                """
                INSERT INTO chat_messages (session_id, role, content, tool_calls)
                VALUES (%s, 'assistant', %s, %s)
                """,
                (session.id, assistant_reply, Jsonb(tool_calls)),
            )
            cur = await conn.execute(
                """
                UPDATE chat_sessions
                SET updated_at = now()
                WHERE id = %s
                RETURNING id, user_id, thread_id, title, created_at, updated_at
                """,
                (session.id,),
            )
            row = await cur.fetchone()

    return _row_to_session(row)


async def list_chat_sessions(
    *,
    user_id: uuid.UUID,
    limit: int = 100,
    offset: int = 0,
) -> list[ChatSessionRecord]:
    async with db_connection() as conn:
        cur = await conn.execute(
            """
            SELECT id, user_id, thread_id, title, created_at, updated_at
            FROM chat_sessions
            WHERE user_id = %s
            ORDER BY updated_at DESC
            LIMIT %s OFFSET %s
            """,
            (user_id, limit, offset),
        )
        rows = await cur.fetchall()

    return [_row_to_session(row) for row in rows]


async def count_chat_sessions(*, user_id: uuid.UUID) -> int:
    async with db_connection() as conn:
        cur = await conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM chat_sessions
            WHERE user_id = %s
            """,
            (user_id,),
        )
        row = await cur.fetchone()

    return row["count"]


async def delete_chat_session(*, user_id: uuid.UUID, thread_id: str) -> bool:
    """Delete one session owned by the user; messages cascade with the session."""
    async with db_connection() as conn:
        cur = await conn.execute(
            """
            DELETE FROM chat_sessions
            WHERE user_id = %s AND thread_id = %s
            RETURNING id
            """,
            (user_id, thread_id),
        )
        row = await cur.fetchone()

    return row is not None


async def list_chat_messages(
    *,
    user_id: uuid.UUID,
    thread_id: str,
    limit: int = 200,
    offset: int = 0,
) -> tuple[ChatSessionRecord | None, list[ChatMessageRecord], int]:
    async with db_connection() as conn:
        cur = await conn.execute(
            """
            SELECT id, user_id, thread_id, title, created_at, updated_at
            FROM chat_sessions
            WHERE user_id = %s AND thread_id = %s
            """,
            (user_id, thread_id),
        )
        session_row = await cur.fetchone()
        if session_row is None:
            return None, [], 0

        session = _row_to_session(session_row)
        cur = await conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM chat_messages
            WHERE session_id = %s
            """,
            (session.id,),
        )
        total = (await cur.fetchone())["count"]
        cur = await conn.execute(
            """
            SELECT id, session_id, role, content, tool_calls, created_at
            FROM chat_messages
            WHERE session_id = %s
            ORDER BY created_at ASC, id ASC
            LIMIT %s OFFSET %s
            """,
            (session.id, limit, offset),
        )
        message_rows = await cur.fetchall()

    return session, [_row_to_message(row) for row in message_rows], total
