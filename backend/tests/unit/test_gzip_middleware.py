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

from app.middleware.compressible_gzip import CompressibleGZipMiddleware


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

    @app.get("/font-woff2")
    def font_woff2():
        return Response(
            content=b"wOF2" + b"\x00" * 4096,
            media_type="font/woff2",
        )

    @app.get("/zip-file")
    def zip_file():
        return Response(
            content=b"PK\x03\x04" + b"\x00" * 4096,
            media_type="application/zip",
        )

    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"])
    app.add_middleware(CompressibleGZipMiddleware, minimum_size=1024)
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
    """二进制 content-type（image/png）应被中间件跳过，不被服务端二次压缩。

    历史背景：starlette 0.41.x GZipMiddleware 不支持 exclude_content_types，
    会主动压所有 ≥1024 B 响应（image/png/font/woff/application/zip 全部中招）；
    starlette 0.42+ 才加 DEFAULT_EXCLUDED_CONTENT_TYPES。fastapi 0.115.6 锁
    starlette<0.42，业务侧用自实现的 CompressibleGZipMiddleware 兜底。
    """
    client = TestClient(_build_app())
    r = client.get("/image-png", headers={"Accept-Encoding": "gzip"})
    assert r.headers.get("content-encoding") is None
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_font_woff2_not_regzipped():
    """font/woff2（已压缩字体）应被中间件跳过。"""
    client = TestClient(_build_app())
    r = client.get("/font-woff2", headers={"Accept-Encoding": "gzip"})
    assert r.headers.get("content-encoding") is None
    assert r.content[:4] == b"wOF2"


def test_zip_not_regzipped():
    """application/zip（已是压缩包）应被中间件跳过。"""
    client = TestClient(_build_app())
    r = client.get("/zip-file", headers={"Accept-Encoding": "gzip"})
    assert r.headers.get("content-encoding") is None
    assert r.content[:4] == b"PK\x03\x04"


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
