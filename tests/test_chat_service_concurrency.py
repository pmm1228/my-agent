import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.core.conversation_lock import ConversationLockManager
from app.agents.contracts import CURRENT_STATE_SCHEMA_VERSION
from app.services import chat_service

class _FakeGraph:
    def __init__(self):
        self.messages = []
        self.interrupts = ()
        self.invoke_count = 0
        self.state_schema_version = CURRENT_STATE_SCHEMA_VERSION
        self.checkpointer = self

    async def aget_state(self, _config):
        return SimpleNamespace(
            values={
                "messages": list(self.messages),
                "state_schema_version": self.state_schema_version,
            },
            interrupts=self.interrupts,
        )

    async def ainvoke(self, inputs, _config):
        self.invoke_count += 1
        await asyncio.sleep(0)
        self.messages.extend(inputs["messages"])
        user_message = inputs["messages"][-1]["content"]
        self.messages.append(SimpleNamespace(content=f"reply:{user_message}"))
        return {"messages": list(self.messages)}

    async def astream_events(self, inputs, config, version):
        result = await self.ainvoke(inputs, config)
        content = result["messages"][-1].content
        yield {
            "event": "on_chat_model_stream",
            "metadata": {"langgraph_node": "chatbot"},
            "data": {"chunk": SimpleNamespace(content=content)},
        }

    async def adelete_thread(self, _thread_id):
        self.messages.clear()


class ChatServiceConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.graph = _FakeGraph()
        self.locks = ConversationLockManager()
        self.patches = [
            patch.object(chat_service, "get_chat_graph", return_value=self.graph),
            patch.object(chat_service, "conversation_locks", self.locks),
        ]
        for active_patch in self.patches:
            active_patch.start()

    def tearDown(self):
        for active_patch in reversed(self.patches):
            active_patch.stop()

    async def test_history_callbacks_follow_agent_order(self):
        first_history_started = asyncio.Event()
        release_first_history = asyncio.Event()
        order = []

        async def save_first(_result):
            order.append("first-history-start")
            first_history_started.set()
            await release_first_history.wait()
            order.append("first-history-end")

        async def save_second(_result):
            order.append("second-history")

        first = asyncio.create_task(
            chat_service.chat(
                "first",
                thread_id="shared",
                user_id="user-1",
                on_completed=save_first,
            )
        )
        await first_history_started.wait()
        second = asyncio.create_task(
            chat_service.chat(
                "second",
                thread_id="shared",
                user_id="user-1",
                on_completed=save_second,
            )
        )
        await asyncio.sleep(0)
        self.assertEqual(order, ["first-history-start"])

        release_first_history.set()
        await asyncio.gather(first, second)

        self.assertEqual(
            order,
            ["first-history-start", "first-history-end", "second-history"],
        )

    async def test_new_chat_does_not_replace_pending_confirmation(self):
        self.graph.interrupts = (
            SimpleNamespace(value={"type": "web_confirmation", "message": "允许联网？"}),
        )

        with self.assertRaises(chat_service.PendingConfirmationError):
            await chat_service.chat(
                "忽略上一个请求",
                thread_id="shared",
                user_id="user-1",
            )

        self.assertEqual(self.graph.invoke_count, 0)

    async def test_new_stream_does_not_replace_pending_confirmation(self):
        self.graph.interrupts = (
            SimpleNamespace(value={"type": "web_confirmation", "message": "允许联网？"}),
        )

        with self.assertRaises(chat_service.PendingConfirmationError):
            async for _ in chat_service.stream_chat(
                "忽略上一个请求",
                thread_id="shared",
                user_id="user-1",
            ):
                pass

        self.assertEqual(self.graph.invoke_count, 0)

    async def test_legacy_checkpoint_is_cleared_before_new_turn(self):
        self.graph.messages = [SimpleNamespace(content="旧旅行状态")]
        self.graph.state_schema_version = None
        reset_history = AsyncMock(return_value=True)

        with self.assertRaises(chat_service.WorkflowResetRequiredError) as raised:
            await chat_service.chat(
                "2个人",
                thread_id="shared",
                user_id="user-1",
                on_state_reset=reset_history,
            )

        self.assertEqual(self.graph.messages, [])
        self.assertEqual(self.graph.invoke_count, 0)
        reset_history.assert_awaited_once_with("shared")
        self.assertTrue(raised.exception.details["history_cleared"])

    async def test_stream_done_is_yielded_after_lock_release(self):
        stream = chat_service.stream_chat(
            "stream",
            thread_id="shared",
            user_id="user-1",
        )
        token = await anext(stream)
        self.assertEqual(token.type, "token")
        done = await anext(stream)
        self.assertEqual(done.type, "done")

        acquired = False
        async with self.locks.acquire("user:user-1:thread:shared"):
            acquired = True
        self.assertTrue(acquired)
        await stream.aclose()

    async def test_delete_waits_for_active_chat(self):
        chat_started = asyncio.Event()
        release_chat = asyncio.Event()
        delete_finished = asyncio.Event()

        async def hold_chat(_result):
            chat_started.set()
            await release_chat.wait()

        chat_task = asyncio.create_task(
            chat_service.chat(
                "active",
                thread_id="shared",
                user_id="user-1",
                on_completed=hold_chat,
            )
        )
        await chat_started.wait()

        async def delete():
            await chat_service.delete_thread_history(
                thread_id="shared",
                user_id="user-1",
            )
            delete_finished.set()

        delete_task = asyncio.create_task(delete())
        await asyncio.sleep(0)
        self.assertFalse(delete_finished.is_set())

        release_chat.set()
        await asyncio.gather(chat_task, delete_task)
        self.assertTrue(delete_finished.is_set())

    async def test_delete_removes_persistent_history_before_checkpoint(self):
        order = []

        async def delete_history():
            order.append("history")
            return True

        async def delete_checkpoint(_thread_id):
            order.append("checkpoint")

        self.graph.adelete_thread = delete_checkpoint
        deleted = await chat_service.delete_thread_history(
            thread_id="shared",
            user_id="user-1",
            delete_persistent_history=delete_history,
        )

        self.assertTrue(deleted)
        self.assertEqual(order, ["history", "checkpoint"])


if __name__ == "__main__":
    unittest.main()
