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
    client = TestClient(_build_app())
    r = client.get("/image-png", headers={"Accept-Encoding": "gzip"})
    assert r.headers.get("content-encoding") is None


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
