import ipaddress
import re
import socket
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from langchain_core.tools import tool

from app.core.config import get_settings
from app.utils.http import http_client


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.ignored = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self.ignored += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self.ignored:
            self.ignored -= 1

    def handle_data(self, data: str) -> None:
        if not self.ignored and data.strip():
            self.parts.append(data.strip())


def _validate_public_url(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("只支持公开的 HTTP/HTTPS URL")
    if parsed.username or parsed.password:
        raise ValueError("URL 不得包含用户名或密码")

    try:
        addresses = {
            ipaddress.ip_address(item[4][0])
            for item in socket.getaddrinfo(
                parsed.hostname,
                parsed.port or (443 if parsed.scheme == "https" else 80),
            )
        }
    except socket.gaierror as exc:
        raise ValueError("无法解析网页域名") from exc
    if not addresses or any(not address.is_global for address in addresses):
        raise ValueError("禁止访问本机、内网或保留地址")


def _html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    return re.sub(r"\s+", " ", " ".join(parser.parts)).strip()


@tool
def fetch_webpage(url: str) -> str:
    """读取一个公开网页的正文。仅当搜索摘要不足，或用户明确给出网页链接时调用。"""
    settings = get_settings()
    current_url = url.strip()
    try:
        with http_client() as client:
            for _ in range(4):
                _validate_public_url(current_url)
                response = client.get(current_url, follow_redirects=False)
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        raise ValueError("网页重定向缺少目标地址")
                    current_url = urljoin(current_url, location)
                    continue
                response.raise_for_status()
                break
            else:
                raise ValueError("网页重定向次数过多")

        content_type = response.headers.get("content-type", "").lower()
        if "text/html" not in content_type and "text/plain" not in content_type:
            return f"不支持读取该内容类型：{content_type or '未知'}"
        raw = response.content[: settings.WEB_PAGE_MAX_BYTES]
        text = raw.decode(response.encoding or "utf-8", errors="replace")
        if "text/html" in content_type:
            text = _html_to_text(text)
        return f"来源：{current_url}\n正文：\n{text}" if text else "网页没有可读取的正文。"
    except Exception as exc:
        return f"网页读取失败：{exc}"
