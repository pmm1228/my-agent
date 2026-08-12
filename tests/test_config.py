import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.core.config import get_settings


class ConfigValidationTests(unittest.TestCase):
    def setUp(self):
        get_settings.cache_clear()

    def tearDown(self):
        get_settings.cache_clear()

    def test_conversation_lock_timeout_must_be_positive(self):
        settings = SimpleNamespace(
            DEEPSEEK_API_KEY="key",
            CONVERSATION_LOCK_TIMEOUT_SECONDS=0,
        )
        with patch("app.core.config.Settings", return_value=settings):
            with self.assertRaisesRegex(RuntimeError, "TIMEOUT_SECONDS"):
                get_settings()


if __name__ == "__main__":
    unittest.main()
