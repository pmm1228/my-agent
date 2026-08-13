import asyncio

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver

from app.core.config import get_settings


async def _close_pool_safely(pool) -> None:
    try:
        await pool.close()
    except Exception:
        pass


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
            try:
                await pool.open()
                saver = AsyncPostgresSaver(pool)
                await saver.setup()
            except Exception:
                await _close_pool_safely(pool)
                raise
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

    async def asetup(self):
        await self._ensure_saver()

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


def get_checkpoint_database_url() -> str:
    return get_settings().POSTGRES_URL


async def init_checkpointer_storage() -> bool:
    """Create or migrate persistent checkpoint tables when PostgreSQL is enabled."""
    if get_settings().CHECKPOINTER_TYPE != "postgres":
        return False

    checkpointer = get_checkpointer()
    try:
        setup = getattr(checkpointer, "asetup", None)
        if setup is not None:
            await setup()
        return True
    finally:
        close = getattr(checkpointer, "aclose", None)
        if close is not None:
            await close()


async def reset_checkpoint_data() -> dict[str, int]:
    """Clear LangGraph checkpoint rows using POSTGRES_URL directly."""
    conn_string = get_checkpoint_database_url()
    if not conn_string:
        return {}

    try:
        from psycopg.rows import dict_row
        from psycopg_pool import AsyncConnectionPool
    except ImportError as exc:
        raise RuntimeError(
            "重置 checkpoint 需要安装 psycopg_pool 和 psycopg[binary]"
        ) from exc

    tables = ("checkpoint_writes", "checkpoint_blobs", "checkpoints")
    pool = AsyncConnectionPool(
        conn_string,
        open=False,
        kwargs={"autocommit": True, "row_factory": dict_row},
    )
    try:
        await pool.open()
        cleared: dict[str, int] = {}
        async with pool.connection() as conn:
            async with conn.transaction():
                existing = []
                for table_name in tables:
                    cur = await conn.execute(
                        "SELECT to_regclass(%s) AS table_name",
                        (f"public.{table_name}",),
                    )
                    row = await cur.fetchone()
                    if not row or row["table_name"] is None:
                        continue
                    existing.append(table_name)
                    cur = await conn.execute(
                        f"SELECT COUNT(*) AS count FROM {table_name}"
                    )
                    cleared[table_name] = (await cur.fetchone())["count"]
                if existing:
                    await conn.execute(f"TRUNCATE TABLE {', '.join(existing)}")
        return cleared
    finally:
        await _close_pool_safely(pool)


async def delete_user_checkpoint_data(user_id: str) -> None:
    """Delete all persistent checkpoint rows owned by one user."""
    settings = get_settings()
    conn_string = get_checkpoint_database_url()
    if settings.CHECKPOINTER_TYPE != "postgres" or not conn_string:
        return

    try:
        from psycopg.rows import dict_row
        from psycopg_pool import AsyncConnectionPool
    except ImportError as exc:
        raise RuntimeError(
            "删除用户 checkpoint 需要安装 psycopg_pool 和 psycopg[binary]"
        ) from exc

    pool = AsyncConnectionPool(
        conn_string,
        open=False,
        kwargs={"autocommit": True, "row_factory": dict_row},
    )
    prefix = f"user:{user_id}:thread:%"
    try:
        await pool.open()
        async with pool.connection() as conn:
            async with conn.transaction():
                for table_name in (
                    "checkpoint_writes",
                    "checkpoint_blobs",
                    "checkpoints",
                ):
                    cur = await conn.execute(
                        "SELECT to_regclass(%s) AS table_name",
                        (f"public.{table_name}",),
                    )
                    row = await cur.fetchone()
                    if not row or row["table_name"] is None:
                        continue
                    await conn.execute(
                        f"DELETE FROM {table_name} WHERE thread_id LIKE %s",
                        (prefix,),
                    )
    finally:
        await _close_pool_safely(pool)
