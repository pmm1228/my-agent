import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.tools.search.tavily import search_web
from app.tools.search.webpage import _html_to_text, _validate_public_url


class SearchToolTests(unittest.TestCase):
    def test_search_requires_api_key(self):
        settings = SimpleNamespace(TAVILY_API_KEY="", WEB_SEARCH_MAX_RESULTS=5)
        with patch("app.tools.search.tavily.get_settings", return_value=settings):
            result = search_web.invoke({"query": "test"})
        self.assertIn("TAVILY_API_KEY", result)

    def test_search_returns_structured_sources(self):
        response = MagicMock()
        response.json.return_value = {
            "results": [{"title": "标题", "url": "https://example.com", "content": "摘要"}]
        }
        client = MagicMock()
        client.post.return_value = response
        manager = MagicMock()
        manager.__enter__.return_value = client
        settings = SimpleNamespace(TAVILY_API_KEY="key", WEB_SEARCH_MAX_RESULTS=5)
        with (
            patch("app.tools.search.tavily.get_settings", return_value=settings),
            patch("app.tools.search.tavily.http_client", return_value=manager),
        ):
            result = search_web.invoke({"query": "测试"})
        self.assertEqual(json.loads(result)[0]["url"], "https://example.com")

    def test_private_address_is_rejected(self):
        with patch("app.tools.search.webpage.socket.getaddrinfo", return_value=[
            (None, None, None, None, ("127.0.0.1", 80))
        ]):
            with self.assertRaisesRegex(ValueError, "内网"):
                _validate_public_url("http://example.test/private")

    def test_html_to_text_ignores_script_and_style(self):
        text = _html_to_text("<h1>标题</h1><script>bad()</script><p>正文</p>")
        self.assertEqual(text, "标题 正文")


if __name__ == "__main__":
    unittest.main()
