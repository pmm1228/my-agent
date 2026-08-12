import asyncio
import unittest
from unittest.mock import patch

from app.core.conversation_lock import (
    ConversationLockManager,
    ConversationLockTimeout,
)


class ConversationLockManagerTests(unittest.IsolatedAsyncioTestCase):
    async def test_same_thread_is_serialized(self):
        manager = ConversationLockManager()
        first_entered = asyncio.Event()
        release_first = asyncio.Event()
        order = []

        async def first():
            async with manager.acquire("thread-1"):
                order.append("first-enter")
                first_entered.set()
                await release_first.wait()
                order.append("first-exit")

        async def second():
            await first_entered.wait()
            async with manager.acquire("thread-1"):
                order.append("second-enter")

        first_task = asyncio.create_task(first())
        second_task = asyncio.create_task(second())
        await first_entered.wait()
        await asyncio.sleep(0)
        self.assertEqual(order, ["first-enter"])

        release_first.set()
        await asyncio.gather(first_task, second_task)

        self.assertEqual(order, ["first-enter", "first-exit", "second-enter"])
        self.assertEqual(manager._entries, {})

    async def test_different_threads_can_run_concurrently(self):
        manager = ConversationLockManager()
        both_entered = asyncio.Event()
        entered = set()

        async def run(thread_key: str):
            async with manager.acquire(thread_key):
                entered.add(thread_key)
                if len(entered) == 2:
                    both_entered.set()
                await asyncio.wait_for(both_entered.wait(), timeout=1)

        await asyncio.gather(run("thread-1"), run("thread-2"))

        self.assertEqual(entered, {"thread-1", "thread-2"})
        self.assertEqual(manager._entries, {})

    async def test_local_lock_wait_times_out(self):
        manager = ConversationLockManager()
        holder_entered = asyncio.Event()
        release_holder = asyncio.Event()

        async def holder():
            async with manager.acquire("thread-1"):
                holder_entered.set()
                await release_holder.wait()

        settings = type(
            "Settings",
            (),
            {"CONVERSATION_LOCK_TIMEOUT_SECONDS": 0.01},
        )()
        with patch("app.core.conversation_lock.get_settings", return_value=settings):
            holder_task = asyncio.create_task(holder())
            await holder_entered.wait()
            with self.assertRaises(ConversationLockTimeout):
                async with manager.acquire("thread-1"):
                    pass
            release_holder.set()
            await holder_task

        self.assertEqual(manager._entries, {})

    async def test_cancelled_waiter_does_not_leak_lock_entry(self):
        manager = ConversationLockManager()
        holder_entered = asyncio.Event()
        release_holder = asyncio.Event()

        async def holder():
            async with manager.acquire("thread-1"):
                holder_entered.set()
                await release_holder.wait()

        async def waiter():
            async with manager.acquire("thread-1"):
                pass

        holder_task = asyncio.create_task(holder())
        await holder_entered.wait()
        waiter_task = asyncio.create_task(waiter())
        await asyncio.sleep(0)
        waiter_task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await waiter_task

        release_holder.set()
        await holder_task
        self.assertEqual(manager._entries, {})

    async def test_body_timeout_is_not_reclassified_as_lock_timeout(self):
        manager = ConversationLockManager()

        try:
            async with manager.acquire("thread-1"):
                raise TimeoutError("agent timeout")
        except Exception as exc:
            caught = exc

        self.assertIs(type(caught), TimeoutError)
        self.assertEqual(str(caught), "agent timeout")


if __name__ == "__main__":
    unittest.main()
