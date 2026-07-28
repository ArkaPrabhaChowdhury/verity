from __future__ import annotations

import asyncio
import ipaddress
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from .models import Document
from .providers import ProviderHTTPError

MAX_HTML_BYTES = 4 << 20
BLOCKED_ELEMENTS = {"script", "style", "noscript", "svg", "nav", "footer", "form", "aside"}


def _is_unsafe_ip(value: str) -> bool:
    address = ipaddress.ip_address(value)
    return any(
        (
            address.is_private,
            address.is_loopback,
            address.is_link_local,
            address.is_multicast,
            address.is_unspecified,
            address.is_reserved,
        )
    )


async def validate_public_url(raw_url: str) -> None:
    parsed = urlparse(raw_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username:
        raise ValueError("invalid public URL")
    host = parsed.hostname.lower()
    if host == "localhost" or host.endswith((".localhost", ".local")):
        raise ValueError("refusing local URL")
    try:
        if _is_unsafe_ip(host):
            raise ValueError("refusing non-public address")
        return
    except ValueError:
        pass
    loop = asyncio.get_running_loop()
    addresses = await loop.getaddrinfo(
        host,
        parsed.port or (443 if parsed.scheme == "https" else 80),
    )
    if not addresses:
        raise ValueError(f"no address found for {host}")
    if any(_is_unsafe_ip(item[4][0]) for item in addresses):
        raise ValueError(f"refusing non-public address for {host}")


class Extractor:
    def __init__(self, client: httpx.AsyncClient, max_text: int = 1800) -> None:
        self.client = client
        self.max_text = max_text

    async def fetch(self, raw_url: str) -> Document:
        current = raw_url
        for _ in range(6):
            await validate_public_url(current)
            response = await self.client.get(
                current,
                headers={
                    "User-Agent": "VerityResearchBot/2.0 (+https://github.com/ArkaPrabhaChowdhury/verity)",
                    "Accept": "text/html,application/xhtml+xml",
                },
                follow_redirects=False,
            )
            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    raise RuntimeError("redirect missing location")
                current = urljoin(current, location)
                continue
            if not response.is_success:
                raise ProviderHTTPError(response.status_code, "page fetch failed")
            content_type = response.headers.get("content-type", "")
            if content_type and not any(
                allowed in content_type for allowed in ("text/html", "application/xhtml")
            ):
                raise ValueError(f"unsupported content type {content_type!r}")
            content = response.content[:MAX_HTML_BYTES]
            soup = BeautifulSoup(content, "html.parser")
            for node in soup.find_all(list(BLOCKED_ELEMENTS)):
                node.decompose()
            title = soup.title.get_text(" ", strip=True) if soup.title else ""
            text = "\n".join(
                part.strip()
                for part in soup.get_text("\n").splitlines()
                if len(part.strip()) > 1
            )
            if len(text) < 160:
                raise ValueError("insufficient extractable content")
            return Document(url=str(response.url), title=title, text=text[: self.max_text])
        raise RuntimeError("too many redirects")
