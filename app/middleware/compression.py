"""Brotli / gzip response compression (pure ASGI, so it wraps every response).

Brotli is preferred when the client accepts it (~15-20% smaller than gzip for
HTML/JSON/CSS/JS). Only compressible content types above a size threshold are
compressed; file downloads (PDF, images) and already-encoded bodies pass through.
In production nginx can also compress static files; doing it here keeps the API
compressed even without nginx.
"""
from __future__ import annotations

import gzip

import brotli
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_COMPRESSIBLE = ("text/", "application/json", "application/javascript", "image/svg+xml", "application/xml")
MIN_SIZE = 500
_MAX_BUFFER = 4 * 1024 * 1024


class CompressionMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        accept = Headers(scope=scope).get("accept-encoding", "").lower()
        encoding = "br" if "br" in accept else "gzip" if "gzip" in accept else None
        if encoding is None:
            await self.app(scope, receive, send)
            return

        start: Message | None = None
        chunks: list[bytes] = []
        passthrough = False
        size = 0

        async def wrapped_send(message: Message) -> None:
            nonlocal start, passthrough, size
            if message["type"] == "http.response.start":
                headers = Headers(raw=message["headers"])
                ctype = headers.get("content-type", "")
                if headers.get("content-encoding") or not ctype.startswith(_COMPRESSIBLE):
                    passthrough = True
                    await send(message)
                else:
                    start = message
                return
            if message["type"] != "http.response.body" or passthrough:
                await send(message)
                return

            chunks.append(message.get("body", b""))
            size += len(chunks[-1])
            if message.get("more_body", False):
                if size > _MAX_BUFFER:  # very large stream: give up compressing, flush as-is
                    passthrough = True
                    assert start is not None
                    await send(start)
                    await send({"type": "http.response.body", "body": b"".join(chunks), "more_body": True})
                    chunks.clear()
                return

            body = b"".join(chunks)
            assert start is not None
            headers = MutableHeaders(raw=start["headers"])
            if len(body) >= MIN_SIZE and start["status"] not in (204, 304):
                body = brotli.compress(body, quality=5) if encoding == "br" else gzip.compress(body, compresslevel=6)
                headers["Content-Encoding"] = encoding
                headers["Content-Length"] = str(len(body))
                vary = headers.get("vary")
                headers["Vary"] = f"{vary}, Accept-Encoding" if vary else "Accept-Encoding"
                if "etag" in headers and not headers["etag"].startswith("W/"):
                    headers["ETag"] = "W/" + headers["etag"]  # body bytes changed
            await send(start)
            await send({"type": "http.response.body", "body": body})

        await self.app(scope, receive, wrapped_send)
