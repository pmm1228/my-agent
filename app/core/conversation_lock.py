import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator

from app.core.config import get_settings


class ConversationLockTimeout(TimeoutError):
    """Raised when the same conversation remains busy past the wait limit."""


@dataclass
class _LockEntry:
    lock: asyncio.Lock
    references: int = 0


class ConversationLockManager:
    """Serialize turns for one checkpoint thread within this process."""

    def __init__(self) -> None:
        self._entries: dict[str, _LockEntry] = {}
        self._entries_lock = asyncio.Lock()

    async def _reference_entry(self, thread_key: str) -> _LockEntry:
        async with self._entries_lock:
            entry = self._entries.get(thread_key)
            if entry is None:
                entry = _LockEntry(lock=asyncio.Lock())
                self._entries[thread_key] = entry
            entry.references += 1
            return entry

    async def _dereference_entry(self, thread_key: str, entry: _LockEntry) -> None:
        async with self._entries_lock:
            entry.references -= 1
            if entry.references == 0 and not entry.lock.locked():
                self._entries.pop(thread_key, None)

    @asynccontextmanager
    async def acquire(self, thread_key: str) -> AsyncIterator[None]:
        entry = await self._reference_entry(thread_key)
        acquired = False
        timeout = get_settings().CONVERSATION_LOCK_TIMEOUT_SECONDS
        try:
            try:
                async with asyncio.timeout(timeout):
                    await entry.lock.acquire()
            except TimeoutError as exc:
                raise ConversationLockTimeout(
                    f"会话锁等待超过 {timeout:g} 秒"
                ) from exc

            acquired = True
            yield
        finally:
            if acquired:
                entry.lock.release()
            await self._dereference_entry(thread_key, entry)


conversation_locks = ConversationLockManager()
