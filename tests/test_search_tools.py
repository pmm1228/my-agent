import json
import ipaddress
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.tools.search.tavily import search_web
from app.tools.search.webpage import (
    _html_to_text,
    _validate_public_url,
    fetch_webpage_text,
)


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

    def test_explicit_reserved_ip_is_rejected_even_when_proxy_range_is_allowed(self):
        settings = SimpleNamespace(WEB_ALLOWED_PROXY_CIDRS="198.18.0.0/15")
        with patch("app.tools.search.webpage.get_settings", return_value=settings):
            with self.assertRaisesRegex(ValueError, "不得直接使用"):
                _validate_public_url("http://198.18.0.94/private")

    def test_proxy_synthesized_dns_still_checks_public_dns_target(self):
        settings = SimpleNamespace(WEB_ALLOWED_PROXY_CIDRS="198.18.0.0/15")
        with (
            patch("app.tools.search.webpage.get_settings", return_value=settings),
            patch("app.tools.search.webpage.socket.getaddrinfo", return_value=[
                (None, None, None, None, ("198.18.0.95", 80))
            ]),
            patch(
                "app.tools.search.webpage._resolve_addresses_via_public_doh",
                return_value={ipaddress.ip_address("127.0.0.1")},
            ),
        ):
            with self.assertRaisesRegex(ValueError, "公共 DNS"):
                _validate_public_url("http://127.0.0.1.nip.io")

    def test_html_to_text_ignores_script_and_style(self):
        text = _html_to_text("<h1>标题</h1><script>bad()</script><p>正文</p>")
        self.assertEqual(text, "标题 正文")

    def test_page_reader_checks_connected_peer_and_streams_with_limit(self):
        stream = MagicMock()
        stream.get_extra_info.return_value = ("93.184.216.34", 443)
        response = MagicMock()
        response.extensions = {"network_stream": stream}
        response.status_code = 200
        response.headers = {"content-type": "text/plain"}
        response.encoding = "utf-8"
        response.iter_bytes.return_value = [b"hello", b" world"]
        client = MagicMock()
        client.stream.return_value.__enter__.return_value = response
        manager = MagicMock()
        manager.__enter__.return_value = client
        settings = SimpleNamespace(WEB_PAGE_MAX_BYTES=20)
        with (
            patch("app.tools.search.webpage.get_settings", return_value=settings),
            patch("app.tools.search.webpage.http_client", return_value=manager),
            patch("app.tools.search.webpage.socket.getaddrinfo", return_value=[
                (None, None, None, None, ("93.184.216.34", 443))
            ]),
        ):
            result = fetch_webpage_text("https://example.com/page")
        self.assertEqual(result["text"], "hello world")
        client.stream.assert_called_once()

    def test_page_reader_rejects_rebound_private_peer(self):
        stream = MagicMock()
        stream.get_extra_info.return_value = ("127.0.0.1", 443)
        response = MagicMock()
        response.extensions = {"network_stream": stream}
        response.status_code = 200
        response.headers = {"content-type": "text/plain"}
        client = MagicMock()
        client.stream.return_value.__enter__.return_value = response
        manager = MagicMock()
        manager.__enter__.return_value = client
        settings = SimpleNamespace(WEB_PAGE_MAX_BYTES=20)
        with (
            patch("app.tools.search.webpage.get_settings", return_value=settings),
            patch("app.tools.search.webpage.http_client", return_value=manager),
            patch("app.tools.search.webpage.socket.getaddrinfo", return_value=[
                (None, None, None, None, ("93.184.216.34", 443))
            ]),
        ):
            with self.assertRaisesRegex(ValueError, "禁止连接"):
                fetch_webpage_text("https://example.com/page")

    def test_page_reader_stops_when_stream_exceeds_limit(self):
        stream = MagicMock()
        stream.get_extra_info.return_value = ("93.184.216.34", 443)
        response = MagicMock()
        response.extensions = {"network_stream": stream}
        response.status_code = 200
        response.headers = {"content-type": "text/plain"}
        response.iter_bytes.return_value = [b"12345", b"67890"]
        client = MagicMock()
        client.stream.return_value.__enter__.return_value = response
        manager = MagicMock()
        manager.__enter__.return_value = client
        settings = SimpleNamespace(WEB_PAGE_MAX_BYTES=8)
        with (
            patch("app.tools.search.webpage.get_settings", return_value=settings),
            patch("app.tools.search.webpage.http_client", return_value=manager),
            patch("app.tools.search.webpage.socket.getaddrinfo", return_value=[
                (None, None, None, None, ("93.184.216.34", 443))
            ]),
        ):
            with self.assertRaisesRegex(ValueError, "超过"):
                fetch_webpage_text("https://example.com/page")


if __name__ == "__main__":
    unittest.main()
