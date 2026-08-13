import ipaddress
import re
import socket
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from langchain_core.tools import tool

from app.core.config import get_settings
from app.utils.http import http_client


def _allowed_proxy_networks() -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    raw = getattr(get_settings(), "WEB_ALLOWED_PROXY_CIDRS", "")
    networks = []
    for item in raw.split(","):
        value = item.strip()
        if value:
            networks.append(ipaddress.ip_network(value, strict=True))
    return networks


def _address_is_allowed(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return address.is_global or any(
        address in network for network in _allowed_proxy_networks()
    )


def _resolve_addresses_via_public_doh(hostname: str) -> set:
    """Resolve through a trusted public resolver when Docker masks the real peer."""
    hostname = hostname.encode("idna").decode("ascii")
    addresses = set()
    with http_client() as client:
        for record_type in ("A", "AAAA"):
            response = client.get(
                "https://cloudflare-dns.com/dns-query",
                params={"name": hostname, "type": record_type},
                headers={"accept": "application/dns-json"},
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("Status") != 0:
                continue
            for answer in payload.get("Answer") or []:
                if answer.get("type") not in {1, 28}:
                    continue
                try:
                    addresses.add(ipaddress.ip_address(answer.get("data", "")))
                except ValueError:
                    continue
    return addresses


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
        literal_address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        literal_address = None
    if literal_address is not None and not literal_address.is_global:
        raise ValueError("URL 不得直接使用本机、内网或保留地址")

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
    if not addresses or any(not _address_is_allowed(address) for address in addresses):
        raise ValueError("禁止访问本机、内网或保留地址")
    if any(not address.is_global for address in addresses):
        public_addresses = _resolve_addresses_via_public_doh(parsed.hostname)
        if not public_addresses or any(
            not address.is_global for address in public_addresses
        ):
            raise ValueError("公共 DNS 校验发现本机、内网或保留地址")


def _validate_response_peer(response) -> None:
    """Verify the address actually connected to, closing the DNS-rebinding gap."""
    network_stream = response.extensions.get("network_stream")
    peer = (
        network_stream.get_extra_info("server_addr")
        if network_stream is not None else None
    )
    if not peer:
        raise ValueError("无法核验网页服务器地址")
    try:
        address = ipaddress.ip_address(peer[0])
    except ValueError as exc:
        raise ValueError("网页服务器地址无效") from exc
    if not _address_is_allowed(address):
        raise ValueError("禁止连接本机、内网或保留地址")


def _html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    return re.sub(r"\s+", " ", " ".join(parser.parts)).strip()


def fetch_webpage_text(url: str) -> dict:
    """Read one public page for workflow callers and return structured text."""
    settings = get_settings()
    current_url = url.strip()
    with http_client() as client:
        for _ in range(4):
            _validate_public_url(current_url)
            with client.stream("GET", current_url, follow_redirects=False) as response:
                _validate_response_peer(response)
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        raise ValueError("网页重定向缺少目标地址")
                    current_url = urljoin(current_url, location)
                    continue
                response.raise_for_status()
                content_type = response.headers.get("content-type", "").lower()
                if "text/html" not in content_type and "text/plain" not in content_type:
                    raise ValueError(f"不支持读取该内容类型：{content_type or '未知'}")
                content_length = response.headers.get("content-length")
                if content_length:
                    try:
                        declared_length = int(content_length)
                    except ValueError:
                        declared_length = None
                    if (
                        declared_length is not None
                        and declared_length > settings.WEB_PAGE_MAX_BYTES
                    ):
                        raise ValueError("网页正文超过允许的大小")
                raw = bytearray()
                for chunk in response.iter_bytes(chunk_size=65_536):
                    if len(raw) + len(chunk) > settings.WEB_PAGE_MAX_BYTES:
                        raise ValueError("网页正文超过允许的大小")
                    raw.extend(chunk)
                encoding = response.encoding or "utf-8"
                break
        else:
            raise ValueError("网页重定向次数过多")

    text = bytes(raw).decode(encoding, errors="replace")
    if "text/html" in content_type:
        text = _html_to_text(text)
    if not text:
        raise ValueError("网页没有可读取的正文")
    return {"url": current_url, "text": text}


@tool
def fetch_webpage(url: str) -> str:
    """读取一个公开网页的正文。仅当搜索摘要不足，或用户明确给出网页链接时调用。"""
    try:
        result = fetch_webpage_text(url)
        return f"来源：{result['url']}\n正文：\n{result['text']}"
    except Exception as exc:
        return f"网页读取失败：{exc}"
