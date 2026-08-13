import unittest
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from app.services.user_service import delete_user


class _AsyncContext:
    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, *_args):
        return False


class _Cursor:
    def __init__(self, row=None):
        self.row = row

    async def fetchone(self):
        return self.row


class _Connection:
    def __init__(self, row):
        self.row = row

    def transaction(self):
        return _AsyncContext(self)

    async def execute(self, sql, _params=None):
        normalized = " ".join(sql.split())
        if normalized.startswith("SELECT pg_advisory"):
            return _Cursor()
        if "SELECT id, username" in normalized:
            return _Cursor(self.row)
        if normalized.startswith("DELETE FROM app_users"):
            return _Cursor(self.row)
        raise AssertionError(normalized)


class UserCheckpointCleanupTests(unittest.IsolatedAsyncioTestCase):
    async def test_delete_user_cleans_dedicated_checkpoint_storage(self):
        user_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        row = {
            "id": user_id,
            "username": "traveler",
            "display_name": None,
            "role": "user",
            "is_active": True,
            "created_at": now,
            "updated_at": now,
        }
        connection = _Connection(row)
        cleanup = AsyncMock()
        with (
            patch(
                "app.services.user_service.db_connection",
                return_value=_AsyncContext(connection),
            ),
            patch(
                "app.services.user_service.delete_user_checkpoint_data",
                cleanup,
            ),
        ):
            deleted = await delete_user(user_id)

        cleanup.assert_awaited_once_with(str(user_id))
        self.assertEqual(deleted.id, user_id)


if __name__ == "__main__":
    unittest.main()
