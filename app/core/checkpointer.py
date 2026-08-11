import asyncio

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver

from app.core.config import get_settings


class _PostgresCheckpointerProxy(BaseCheckpointSaver):
    def __init__(self, conn_string: str):
        super().__init__()
        self._conn_string = conn_string
        self._pool = None
        self._saver = None
        self._lock = asyncio.Lock()

    async def _ensure_saver(self):
        if self._saver is not None:
            return self._saver
        async with self._lock:
            if self._saver is not None:
                return self._saver
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
            from psycopg_pool import AsyncConnectionPool

            pool = AsyncConnectionPool(
                self._conn_string,
                open=False,
                kwargs={"autocommit": True},
            )
            await pool.open()
            saver = AsyncPostgresSaver(pool)
            await saver.setup()
            self._pool = pool
            self._saver = saver
            return saver

    async def aclose(self):
        async with self._lock:
            pool = self._pool
            self._pool = None
            self._saver = None
            if pool is not None:
                await pool.close()

    async def aget_tuple(self, config):
        saver = await self._ensure_saver()
        return await saver.aget_tuple(config)

    async def aput(self, config, checkpoint, metadata, new_versions):
        saver = await self._ensure_saver()
        return await saver.aput(config, checkpoint, metadata, new_versions)

    async def aget(self, config):
        saver = await self._ensure_saver()
        return await saver.aget(config)

    async def aput_writes(self, config, writes, task_id, task_path=""):
        saver = await self._ensure_saver()
        return await saver.aput_writes(config, writes, task_id, task_path)

    async def alist(self, config, *, filter=None, before=None, limit=None):
        saver = await self._ensure_saver()
        async for item in saver.alist(config, filter=filter, before=before, limit=limit):
            yield item

    async def adelete_thread(self, thread_id):
        saver = await self._ensure_saver()
        return await saver.adelete_thread(thread_id)

    async def adelete_for_runs(self, run_ids):
        saver = await self._ensure_saver()
        return await saver.adelete_for_runs(run_ids)

    async def acopy_thread(self, source_thread_id, target_thread_id):
        saver = await self._ensure_saver()
        return await saver.acopy_thread(source_thread_id, target_thread_id)

    async def aprune(self, thread_ids, *, strategy="keep_latest"):
        saver = await self._ensure_saver()
        return await saver.aprune(thread_ids, strategy=strategy)

    async def aget_delta_channel_history(self, *, config, channels):
        saver = await self._ensure_saver()
        return await saver.aget_delta_channel_history(config=config, channels=channels)


def get_checkpointer() -> BaseCheckpointSaver:
    s = get_settings()

    if s.CHECKPOINTER_TYPE != "postgres":
        return MemorySaver()

    if not s.POSTGRES_URL:
        raise RuntimeError("CHECKPOINTER_TYPE=postgres 需要设置 POSTGRES_URL")

    try:
        import importlib
        importlib.import_module("psycopg_pool")
        importlib.import_module("langgraph.checkpoint.postgres.aio")
    except ImportError as e:
        raise RuntimeError(
            "CHECKPOINTER_TYPE=postgres 但未安装依赖。"
            "请 pip install langgraph-checkpoint-postgres 'psycopg[binary]' psycopg_pool"
        ) from e

    return _PostgresCheckpointerProxy(s.POSTGRES_URL)
