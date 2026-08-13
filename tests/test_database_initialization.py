import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.core.database import get_pool, reset_chat_history_data


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


class _Connection:
    def __init__(self):
        self.tables = {
            "chat_messages": 4,
            "chat_sessions": 2,
            "checkpoint_writes": 8,
            "checkpoint_blobs": 6,
            "checkpoints": 3,
        }
        self.statements = []

    def transaction(self):
        return _AsyncContext(self)

    async def execute(self, sql, params=None):
        normalized = " ".join(sql.split())
        self.statements.append((normalized, params))
        if normalized.startswith("SELECT to_regclass"):
            table = params[0].split(".", 1)[1]
            return _Cursor({"table_name": table if table in self.tables else None})
        if normalized.startswith("SELECT COUNT(*)"):
            table = normalized.rsplit(" ", 1)[1]
            return _Cursor({"count": self.tables[table]})
        return _Cursor(None)


class _Pool:
    def __init__(self, connection):
        self._connection = connection

    def connection(self):
        return _AsyncContext(self._connection)


class _OpenFailingPool:
    instance = None

    def __init__(self, *_args, **_kwargs):
        self.close_count = 0
        self.__class__.instance = self

    async def open(self):
        raise RuntimeError("cannot connect")

    async def close(self):
        self.close_count += 1


class DatabaseInitializationTests(unittest.IsolatedAsyncioTestCase):
    async def test_reset_preserves_users_and_long_term_memory(self):
        connection = _Connection()
        with patch(
            "app.core.database.get_pool",
            AsyncMock(return_value=_Pool(connection)),
        ):
            cleared = await reset_chat_history_data()

        self.assertEqual(cleared["chat_messages"], 4)
        sql = "\n".join(statement for statement, _ in connection.statements)
        self.assertIn("TRUNCATE TABLE chat_messages, chat_sessions RESTART IDENTITY", sql)
        self.assertNotIn("checkpoint_writes", sql)
        self.assertNotIn("TRUNCATE TABLE app_users", sql)
        self.assertNotIn("TRUNCATE TABLE memory_entries", sql)

    async def test_business_pool_open_failure_is_closed(self):
        modules = {
            "psycopg.rows": SimpleNamespace(dict_row=object()),
            "psycopg_pool": SimpleNamespace(AsyncConnectionPool=_OpenFailingPool),
        }
        with (
            patch.dict(sys.modules, modules),
            patch("app.core.database._pool", None),
            patch(
                "app.core.database.get_database_url",
                return_value="postgresql://business-db/app",
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "cannot connect"):
                await get_pool()

        self.assertEqual(_OpenFailingPool.instance.close_count, 1)


if __name__ == "__main__":
    unittest.main()
