import json
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.api.errors import agent_conflict_exception_handler
from app.api.handlers.chat import (
    handle_chat,
    handle_chat_stream,
    handle_delete_chat_session,
)
from app.api.schemas import ChatRequest
from app.core.conversation_lock import ConversationLockTimeout
from app.services.chat_service import (
    AgentConflictError,
    ChatResult,
    PendingConfirmationError,
    WorkflowResetRequiredError,
)


class ChatLockErrorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.user = SimpleNamespace(id=uuid.uuid4())
        self.request = ChatRequest(message="hello", thread_id="thread-1")

    async def test_chat_lock_timeout_returns_conflict(self):
        with patch(
            "app.api.handlers.chat.chat",
            AsyncMock(side_effect=ConversationLockTimeout()),
        ):
            with self.assertRaises(AgentConflictError) as raised:
                await handle_chat(self.request, user=self.user)

        self.assertEqual(raised.exception.code, "conversation_busy")

    async def test_pending_confirmation_returns_conflict(self):
        error = PendingConfirmationError(
            {"type": "web_confirmation", "message": "允许联网？"}
        )
        with patch(
            "app.api.handlers.chat.chat",
            AsyncMock(side_effect=error),
        ):
            with self.assertRaises(AgentConflictError) as raised:
                await handle_chat(self.request, user=self.user)

        self.assertEqual(raised.exception.code, "pending_confirmation")
        response = await agent_conflict_exception_handler(None, raised.exception)
        payload = json.loads(response.body)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(payload["code"], "pending_confirmation")
        self.assertEqual(
            payload["details"]["confirmation"]["type"],
            "web_confirmation",
        )

    async def test_confirmation_response_reports_history_as_pending(self):
        result = ChatResult(
            reply="",
            thread_id="thread-1",
            status="requires_confirmation",
            confirmation={"type": "web_confirmation"},
        )
        with patch(
            "app.api.handlers.chat.chat",
            AsyncMock(return_value=result),
        ):
            response = await handle_chat(self.request, user=self.user)

        self.assertFalse(response.history_saved)
        self.assertEqual(response.history_status, "pending")

    async def test_stream_pending_confirmation_returns_specific_error(self):
        async def pending_stream(*_args, **_kwargs):
            raise PendingConfirmationError(
                {"type": "web_confirmation", "message": "允许联网？"}
            )
            yield

        with patch("app.api.handlers.chat.stream_chat", pending_stream):
            response = await handle_chat_stream(self.request, user=self.user)
            chunks = [chunk async for chunk in response.body_iterator]

        event = json.loads("".join(chunks))
        self.assertEqual(event["type"], "error")
        self.assertEqual(event["code"], "pending_confirmation")
        self.assertEqual(
            event["details"]["confirmation"]["type"],
            "web_confirmation",
        )

    async def test_workflow_reset_returns_conflict(self):
        with patch(
            "app.api.handlers.chat.chat",
            AsyncMock(side_effect=WorkflowResetRequiredError()),
        ):
            with self.assertRaises(AgentConflictError) as raised:
                await handle_chat(self.request, user=self.user)

        self.assertEqual(raised.exception.code, "workflow_reset_required")

    async def test_stream_workflow_reset_returns_specific_error(self):
        async def reset_stream(*_args, **_kwargs):
            raise WorkflowResetRequiredError()
            yield

        with patch("app.api.handlers.chat.stream_chat", reset_stream):
            response = await handle_chat_stream(self.request, user=self.user)
            chunks = [chunk async for chunk in response.body_iterator]

        event = json.loads("".join(chunks))
        self.assertEqual(event["code"], "workflow_reset_required")

    async def test_delete_lock_timeout_returns_conflict(self):
        with patch(
            "app.api.handlers.chat.delete_thread_history",
            AsyncMock(side_effect=ConversationLockTimeout()),
        ):
            with self.assertRaises(AgentConflictError) as raised:
                await handle_delete_chat_session(
                    user=self.user,
                    thread_id="thread-1",
                )

        self.assertEqual(raised.exception.code, "conversation_busy")

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
