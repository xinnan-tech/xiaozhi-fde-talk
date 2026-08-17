"""SPA 兜底路由：刷新时不存在的路径返回 index.html。"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_spa_fallback_serves_index_for_unknown_get():
    """未知 GET 路径应由 index.html 兜底。"""
    from app.transport.spa_fallback import mount

    # 准备临时 static 目录
    import tempfile, pathlib
    with tempfile.TemporaryDirectory() as tmp:
        static_dir = pathlib.Path(tmp)
        (static_dir / "index.html").write_text("<html>OK</html>")
        # patch 静态目录
        import app.transport.spa_fallback as m
        m.STATIC_DIR = static_dir

        app = FastAPI()
        mount(app)
        client = TestClient(app)
        resp = client.get("/some/spa/route")
        assert resp.status_code == 200
        assert "OK" in resp.text


def test_spa_fallback_passes_through_api():
    """API 路径不应被兜底。"""
    from app.transport.spa_fallback import mount

    app = FastAPI()

    @app.get("/api/test")
    def handler():
        return {"ok": True}

    mount(app)
    client = TestClient(app)
    resp = client.get("/api/test")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}