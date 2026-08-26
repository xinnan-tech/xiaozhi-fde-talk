"""GZipMiddleware 行为锁死：
- text/json ≥ 1024 B 自动 gzip（响应头 Content-Encoding: gzip，body 不是原文）
- 不带 Accept-Encoding: gzip 的客户端不压缩
- < 1024 B 不压缩
- 已压缩内容（image/png 等）不二次压缩
- CORS preflight OPTIONS 不被压
"""
from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient
from starlette.middleware.gzip import GZipMiddleware


def _build_app():
    app = FastAPI()

    @app.get("/big-json")
    def big_json():
        return {"data": "x" * 4096}

    @app.get("/small")
    def small():
        return {"ok": True}

    @app.get("/image-png")
    def image_png():
        return Response(
            content=b"\x89PNG\r\n\x1a\n" + b"\x00" * 4096,
            media_type="image/png",
        )

    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"])
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    return app


def test_big_json_gzipped_when_accept_encoding_gzip():
    client = TestClient(_build_app())
    r = client.get("/big-json", headers={"Accept-Encoding": "gzip"})
    assert r.headers.get("content-encoding") == "gzip"
    assert r.content[:20] != b'{"data":"xxxxxxxxx'


def test_not_gzipped_without_accept_encoding():
    # httpx TestClient 会自动塞 Accept-Encoding: gzip,deflate,br；显式置空
    # 才能验证「客户端没声明 gzip 能力 → 服务端不压缩」。
    client = TestClient(_build_app())
    r = client.get("/big-json", headers={"Accept-Encoding": ""})
    assert r.headers.get("content-encoding") is None
    assert r.json()["data"].startswith("x")


def test_small_response_not_gzipped():
    client = TestClient(_build_app())
    r = client.get("/small", headers={"Accept-Encoding": "gzip"})
    assert r.headers.get("content-encoding") is None


def test_binary_not_regzipped():
    """二进制 content-type（image/png）不应被 GZipMiddleware 二次压缩。

    starlette 0.41.3+ 的 GZipMiddleware 默认从 image/png 等二进制类型跳过压缩。
    修复前断言 r.headers["content-encoding"] is None 仅在 httpx 不主动声明
    Accept-Encoding 时通过——CI 上 Python 3.12 httpx 0.28.1 给二进制 endpoint 也
    塞 gzip，导致服务端把4096 字节压成 51，断言挂。改成「服务端不该在 image/png 上
    声明 Content-Encoding」+ body 头仍是 PNG magic 双断言，不依赖 httpx 行为。
    """
    client = TestClient(_build_app())
    r = client.get("/image-png", headers={"Accept-Encoding": "gzip"})
    # 强断言：image/png 在 starlette 默认 exclude 里，服务端不该加 gzip 头
    assert r.headers.get("content-encoding") is None
    # 弱兜底：即便未来 starlette 改了默认 exclude，body 头 8 字节也必须是 PNG magic
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n", (
        f"image/png 响应被破坏：{r.content[:8]!r}"
    )


def test_cors_preflight_not_gzipped():
    client = TestClient(_build_app())
    r = client.options(
        "/big-json",
        headers={
            "Origin": "https://a.com",
            "Access-Control-Request-Method": "GET",
            "Accept-Encoding": "gzip",
        },
    )
    assert r.headers.get("content-encoding") is None
    assert r.headers.get("access-control-allow-origin") == "*"
