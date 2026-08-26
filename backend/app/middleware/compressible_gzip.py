"""按内容类型挑着压的 GZip 中间件。

业务侧为什么不用 starlette.middleware.gzip.GZipMiddleware：

- starlette 0.41.x（fastapi 0.115.6 锁住的上限）的 GZipMiddleware 不支持
  ``exclude_content_types``——裸压所有 ``>= minimum_size`` 的响应，把 image/png、
  font/woff、application/zip 这些已经压过的格式再压一遍，CPU 烧了还变大。
- starlette 0.42+ 加了 ``DEFAULT_EXCLUDED_CONTENT_TYPES`` 默认排除 image/*
  video/* audio/* 等，但 fastapi 0.115.6 不允许升上去。

所以自己写一个 ASGI 中间件：碰到 gzip-不友好（已压缩）的内容类型就直通，
其余按 size 阈值压缩。30 行复刻 starlette 0.42+ 的语义。
"""
from __future__ import annotations

import gzip
import io
from typing import Iterable

from starlette.types import ASGIApp, Message, Receive, Scope, Send


# 已压缩 / 二进制流，gzip 不友好，跳过压缩。``startswith`` 匹配，``image/``
# 一条覆盖 png/jpeg/gif/webp/avif 等所有 image 子类型。
_EXCLUDED_PREFIXES: tuple[str, ...] = (
    "image/",
    "video/",
    "audio/",
)
_EXCLUDED_EXACT: frozenset[str] = frozenset({
    "font/woff",
    "font/woff2",
    "application/zip",
    "application/x-gzip",
    "application/gzip",
    "application/x-tar",
    "application/pdf",
    "application/octet-stream",
})


def _is_excluded(content_type: str) -> bool:
    """判定 content-type 是否属于「再压是负优化」清单。"""
    ct = content_type.split(";", 1)[0].strip().lower()
    if ct in _EXCLUDED_EXACT:
        return True
    return any(ct.startswith(p) for p in _EXCLUDED_PREFIXES)


def _find_header(headers: Iterable[tuple[bytes, bytes]], name: bytes) -> bytes | None:
    """小工具：从原始 headers 列表里按 name（已 lower）取值。"""
    target = name.lower()
    for k, v in headers:
        if k.lower() == target:
            return v
    return None


class CompressibleGZipMiddleware:
    """语义对齐 starlette 0.42+ GZipMiddleware + 默认 exclude 列表。"""

    def __init__(self, app: ASGIApp, minimum_size: int = 1024) -> None:
        self.app = app
        self.minimum_size = minimum_size

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # 客户端没声明 gzip → 直接 pass，不浪费时间在探测 content-type
        accept_encoding = _find_header(scope.get("headers", []), b"accept-encoding")
        if not accept_encoding or "gzip" not in accept_encoding.decode("latin-1").lower():
            await self.app(scope, receive, send)
            return

        await self._run_with_gzip(scope, receive, send)

    async def _run_with_gzip(self, scope: Scope, receive: Receive, send: Send) -> None:
        state: dict[str, object] = {
            "started": False,
            "type_excluded": False,
            "status": 0,
            "headers": [],
            "raw_body_buf": bytearray(),  # 流式 fallback：缓存原文，最后一起发
        }
        buf = io.BytesIO()
        gz = gzip.GzipFile(mode="wb", fileobj=buf)
        compressing = {"on": True}

        async def _ensure_started(headers: list[tuple[bytes, bytes]]) -> None:
            if not state["started"]:
                state["started"] = True
                await send({
                    "type": "http.response.start",
                    "status": state["status"],
                    "headers": headers,
                })

        async def send_wrapper(message: Message) -> None:
            t = message["type"]
            if t == "http.response.start":
                state["status"] = message["status"]
                state["headers"] = list(message.get("headers", []))
                ct_bytes = _find_header(state["headers"], b"content-type")  # type: ignore[arg-type]
                ct = ct_bytes.decode("latin-1") if ct_bytes else ""
                state["type_excluded"] = _is_excluded(ct)
                if not state["type_excluded"]:
                    state["headers"] = [
                        (k, v) for k, v in state["headers"]  # type: ignore[union-attr]
                        if k.lower() not in (b"content-length",)
                    ] + [(b"vary", b"Accept-Encoding")]
            elif t == "http.response.body":
                if state["type_excluded"]:
                    await _ensure_started(state["headers"])  # type: ignore[arg-type]
                    await send(message)
                    return

                body = message.get("body", b"")
                more = message.get("more_body", False)
                if not compressing["on"]:
                    await _ensure_started(state["headers"])  # type: ignore[arg-type]
                    await send(message)
                    return

                if more:
                    # 流式：业务侧暂无，缓存原文等终态（简化：所有 body 都拿到再发）
                    state["raw_body_buf"].extend(body)  # type: ignore[union-attr]
                    return

                # 最后一帧：拿到完整 body 再判定
                full_body = bytes(state["raw_body_buf"]) + body  # type: ignore[arg-type]
                gz.write(full_body)
                gz.close()
                compressing["on"] = False
                compressed = buf.getvalue()
                # 压缩后比原文大（小 JSON 高熵）或 body 本身就小——不压
                if len(full_body) >= self.minimum_size and len(compressed) < len(full_body):
                    new_headers = [
                        (k, v) for k, v in state["headers"]  # type: ignore[union-attr]
                        if k.lower() not in (b"content-length", b"content-encoding")
                    ] + [
                        (b"content-encoding", b"gzip"),
                        (b"content-length", str(len(compressed)).encode("ascii")),
                    ]
                    await _ensure_started(new_headers)
                    await send({
                        "type": "http.response.body",
                        "body": compressed,
                        "more_body": False,
                    })
                else:
                    await _ensure_started(state["headers"])  # type: ignore[arg-type]
                    await send({
                        "type": "http.response.body",
                        "body": full_body,
                        "more_body": False,
                    })
            else:
                # http.response.pathsend / http.response.trailers 等：透传
                await send(message)

        await self.app(scope, receive, send_wrapper)
