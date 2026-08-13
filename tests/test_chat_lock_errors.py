import json
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from app.api.handlers.chat import (
    handle_chat,
    handle_chat_stream,
    handle_delete_chat_session,
)
from app.api.schemas import ChatRequest
from app.core.conversation_lock import ConversationLockTimeout


class ChatLockErrorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.user = SimpleNamespace(id=uuid.uuid4())
        self.request = ChatRequest(message="hello", thread_id="thread-1")

    async def test_chat_lock_timeout_returns_conflict(self):
        with patch(
            "app.api.handlers.chat.chat",
            AsyncMock(side_effect=ConversationLockTimeout()),
        ):
            with self.assertRaises(HTTPException) as raised:
                await handle_chat(self.request, user=self.user)

        self.assertEqual(raised.exception.status_code, 409)

    async def test_delete_lock_timeout_returns_conflict(self):
        with patch(
            "app.api.handlers.chat.delete_thread_history",
            AsyncMock(side_effect=ConversationLockTimeout()),
        ):
            with self.assertRaises(HTTPException) as raised:
                await handle_delete_chat_session(
                    user=self.user,
                    thread_id="thread-1",
                )

        self.assertEqual(raised.exception.status_code, 409)

    async def test_stream_lock_timeout_returns_busy_event(self):
        async def timed_out_stream(*_args, **_kwargs):
            raise ConversationLockTimeout()
            yield

        with patch("app.api.handlers.chat.stream_chat", timed_out_stream):
            response = await handle_chat_stream(self.request, user=self.user)
            chunks = [chunk async for chunk in response.body_iterator]

        event = json.loads("".join(chunks))
        self.assertEqual(event["type"], "error")
        self.assertEqual(event["code"], "conversation_busy")


if __name__ == "__main__":
    unittest.main()
