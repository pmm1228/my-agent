import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.core.checkpointer import (
    _PostgresCheckpointerProxy,
    delete_user_checkpoint_data,
    reset_checkpoint_data,
)


class _FakePool:
    instances = []

    def __init__(self, *_args, **_kwargs):
        self.close_count = 0
        self.__class__.instances.append(self)

    async def open(self):
        return None

    async def close(self):
        self.close_count += 1


class _AsyncContext:
    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, *_args):
        return False


class _Cursor:
    def __init__(self, row):
        self.row = row

    async def fetchone(self):
        return self.row


class _ResetConnection:
    def __init__(self):
        self.counts = {
            "checkpoint_writes": 5,
            "checkpoint_blobs": 4,
            "checkpoints": 3,
        }
        self.statements = []

    def transaction(self):
        return _AsyncContext(self)

    async def execute(self, sql, params=None):
        normalized = " ".join(sql.split())
        self.statements.append(normalized)
        if normalized.startswith("SELECT to_regclass"):
            table = params[0].split(".", 1)[1]
            return _Cursor({"table_name": table})
        if normalized.startswith("SELECT COUNT(*)"):
            table = normalized.rsplit(" ", 1)[1]
            return _Cursor({"count": self.counts[table]})
        return _Cursor(None)


class _ResetPool:
    instance = None

    def __init__(self, *_args, **_kwargs):
        self.connection_value = _ResetConnection()
        self.close_count = 0
        self.__class__.instance = self

    async def open(self):
        return None

    async def close(self):
        self.close_count += 1

    def connection(self):
        return _AsyncContext(self.connection_value)


class CheckpointerInitializationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        _FakePool.instances = []

    async def test_setup_failure_closes_local_pool(self):
        class FailingSaver:
            def __init__(self, _pool):
                pass

            async def setup(self):
                raise RuntimeError("migration failed")

        modules = {
            "psycopg_pool": SimpleNamespace(AsyncConnectionPool=_FakePool),
            "langgraph.checkpoint.postgres.aio": SimpleNamespace(
                AsyncPostgresSaver=FailingSaver
            ),
        }
        with patch.dict(sys.modules, modules):
            proxy = _PostgresCheckpointerProxy("postgresql://example")
            with self.assertRaisesRegex(RuntimeError, "migration failed"):
                await proxy.asetup()

        self.assertEqual(_FakePool.instances[0].close_count, 1)

    async def test_failed_setup_can_retry_without_reusing_pool(self):
        attempts = 0

        class RetrySaver:
            def __init__(self, _pool):
                pass

            async def setup(self):
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    raise RuntimeError("temporary")

        modules = {
            "psycopg_pool": SimpleNamespace(AsyncConnectionPool=_FakePool),
            "langgraph.checkpoint.postgres.aio": SimpleNamespace(
                AsyncPostgresSaver=RetrySaver
            ),
        }
        with patch.dict(sys.modules, modules):
            proxy = _PostgresCheckpointerProxy("postgresql://example")
            with self.assertRaises(RuntimeError):
                await proxy.asetup()
            await proxy.asetup()
            await proxy.aclose()

        self.assertEqual(len(_FakePool.instances), 2)
        self.assertEqual([pool.close_count for pool in _FakePool.instances], [1, 1])

    async def test_pool_open_failure_is_closed(self):
        class OpenFailingPool(_FakePool):
            async def open(self):
                raise RuntimeError("cannot connect")

        modules = {
            "psycopg_pool": SimpleNamespace(AsyncConnectionPool=OpenFailingPool),
            "langgraph.checkpoint.postgres.aio": SimpleNamespace(
                AsyncPostgresSaver=object
            ),
        }
        with patch.dict(sys.modules, modules):
            proxy = _PostgresCheckpointerProxy("postgresql://example")
            with self.assertRaisesRegex(RuntimeError, "cannot connect"):
                await proxy.asetup()

        self.assertEqual(OpenFailingPool.instances[-1].close_count, 1)

    async def test_checkpoint_reset_uses_dedicated_storage(self):
        modules = {
            "psycopg": SimpleNamespace(),
            "psycopg.rows": SimpleNamespace(dict_row=object()),
            "psycopg_pool": SimpleNamespace(AsyncConnectionPool=_ResetPool),
        }
        with (
            patch.dict(sys.modules, modules),
            patch(
                "app.core.checkpointer.get_checkpoint_database_url",
                return_value="postgresql://checkpoint-db/checkpoints",
            ),
        ):
            cleared = await reset_checkpoint_data()

        self.assertEqual(cleared["checkpoints"], 3)
        pool = _ResetPool.instance
        sql = "\n".join(pool.connection_value.statements)
        self.assertIn(
            "TRUNCATE TABLE checkpoint_writes, checkpoint_blobs, checkpoints",
            sql,
        )
        self.assertNotIn("chat_sessions", sql)
        self.assertEqual(pool.close_count, 1)

    async def test_user_checkpoint_cleanup_uses_dedicated_storage(self):
        modules = {
            "psycopg": SimpleNamespace(),
            "psycopg.rows": SimpleNamespace(dict_row=object()),
            "psycopg_pool": SimpleNamespace(AsyncConnectionPool=_ResetPool),
        }
        settings = SimpleNamespace(CHECKPOINTER_TYPE="postgres")
        with (
            patch.dict(sys.modules, modules),
            patch("app.core.checkpointer.get_settings", return_value=settings),
            patch(
                "app.core.checkpointer.get_checkpoint_database_url",
                return_value="postgresql://checkpoint-db/checkpoints",
            ),
        ):
            await delete_user_checkpoint_data("user-id")

        pool = _ResetPool.instance
        statements = pool.connection_value.statements
        delete_statements = [sql for sql in statements if sql.startswith("DELETE")]
        self.assertEqual(len(delete_statements), 3)
        self.assertTrue(all("thread_id LIKE" in sql for sql in delete_statements))
        self.assertEqual(pool.close_count, 1)


if __name__ == "__main__":
    unittest.main()
