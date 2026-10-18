"""Image candidate normalization and safe download/decoding of search results."""
from __future__ import annotations

import asyncio
import io
import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpx
from PIL import Image

MAX_BYTES = 8 * 1024 * 1024
TIMEOUT_S = 15.0
MAX_REDIRECTS = 3
MIN_SIDE = 200
FORMATS = {"PNG": ("image/png", "png"), "JPEG": ("image/jpeg", "jpg"), "WEBP": ("image/webp", "webp")}


@dataclass
class Candidate:
    image_url: str
    description: str | None = None
    source_page_url: str | None = None


@dataclass
class Downloaded:
    data: bytes
    media_type: str
    ext: str


def candidates(search: dict) -> list[Candidate]:
    """Tavily returns images as URL strings or {url, description} objects."""
    out: list[Candidate] = []
    seen: set[str] = set()
    for item in search.get("images") or []:
        if isinstance(item, str):
            url, desc, page = item, None, None
        elif isinstance(item, dict):
            url, desc = item.get("url"), item.get("description")
            # Only record a source page if the provider actually returned one.
            page = item.get("source_url") or item.get("page_url")
        else:
            continue
        if isinstance(url, str) and url.startswith(("http://", "https://")) and url not in seen:
            seen.add(url)
            out.append(Candidate(url, desc if isinstance(desc, str) else None,
                                 page if isinstance(page, str) else None))
    return out


async def _public_host(url: str) -> bool:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return False
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(parts.hostname, parts.port or 443,
                                                             type=socket.SOCK_STREAM)
    except OSError:
        return False
    # shortcut: resolve-then-connect leaves a DNS-rebinding window; pin the IP if this ever runs on untrusted infra.
    return bool(infos) and all(ipaddress.ip_address(i[4][0].split("%")[0]).is_global for i in infos)


def decode(data: bytes) -> Downloaded | None:
    try:
        with Image.open(io.BytesIO(data)) as img:
            fmt, size = img.format, img.size
            img.verify()
        with Image.open(io.BytesIO(data)) as img:
            img.load()  # verify() skips pixel data; a full load catches truncated files.
    except Exception:
        return None
    if fmt not in FORMATS or min(size) < MIN_SIDE:
        return None
    media_type, ext = FORMATS[fmt]
    return Downloaded(data, media_type, ext)


async def download(client: httpx.AsyncClient, url: str) -> tuple[Downloaded | None, str]:
    """Returns (image, reason). Never fetches private/loopback addresses, including via redirects."""
    for _ in range(MAX_REDIRECTS + 1):
        if not await _public_host(url):
            return None, f"refused non-public URL {url[:120]}"
        try:
            async with client.stream("GET", url, timeout=TIMEOUT_S) as resp:
                if resp.is_redirect and resp.headers.get("location"):
                    url = urljoin(url, resp.headers["location"])
                    continue
                if resp.status_code != 200:
                    return None, f"HTTP {resp.status_code}"
                if int(resp.headers.get("content-length") or 0) > MAX_BYTES:
                    return None, "image too large"
                buf = bytearray()
                async for chunk in resp.aiter_bytes():
                    buf += chunk
                    if len(buf) > MAX_BYTES:
                        return None, "image too large"
        except (httpx.HTTPError, ValueError) as exc:
            return None, f"download failed: {type(exc).__name__}"
        img = decode(bytes(buf))
        return (img, "ok") if img else (None, f"not a decodable PNG/JPEG/WebP of at least {MIN_SIDE}px")
    return None, "too many redirects"


def make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(follow_redirects=False, headers={"User-Agent": "nebius-reel/1.0"})
