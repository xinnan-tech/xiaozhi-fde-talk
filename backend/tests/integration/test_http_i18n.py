# tests/integration/test_http_i18n.py
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(en_locale):
    from app.app import create_app
    return TestClient(create_app())


@pytest.fixture
def auth_client(en_locale):
    """TestClient with `get_current_user` overridden to a fake admin user, so
    auth-protected routes (templates, interviews) reach the I18nError raise
    sites without a real JWT login round-trip.
    """
    from app.app import create_app
    from app.domain.auth import CurrentUser
    from app.transport.http.dependencies import get_current_user

    app = create_app()

    async def _fake_user() -> CurrentUser:
        return CurrentUser(user_id="test-user-id", username="admin", role="admin")

    app.dependency_overrides[get_current_user] = _fake_user
    return TestClient(app)


def test_content_language_header_set_in_each_locale():
    """Scaffolding test: validate I18nHTTPMiddleware (T05) writes
    Content-Language on every response.

    Exercises `create_app()` against the real `/health` GET endpoint (no auth,
    no DB dependency at the route layer). Brief suggested `/api/health` which
    does not exist in this codebase; the only matching GETs at the app
    root-level are `/health` and `/ready`. We use `/health`.

    Will be expanded in T07-T12 once adapters/routes start raising I18nError
    and the exception handler becomes load-bearing.
    """
    from app.app import create_app

    for lang in ("zh-CN", "zh-TW", "en-US"):
        app = create_app()
        c = TestClient(app)
        r = c.get("/health", headers={"Accept-Language": lang})
        assert r.headers.get("Content-Language") in {"zh-CN", "zh-TW", "en-US"}, (
            f"Content-Language not set for Accept-Language: {lang}; "
            f"got headers={dict(r.headers)}"
        )


# ---- T10: HTTP route localization ----
# Rate-limiter is module-global in app.transport.http.routes.auth; reset it
# before each test so test order doesn't matter (capacity=5, refill_per_hour=300
# would otherwise leak tokens across runs of `test_rate_limit_zh_tw` and
# `test_invalid_credentials_localized`).
@pytest.fixture(autouse=True)
def _reset_login_rate_limiter():
    from app.transport.http.routes.auth import _login_limiter

    _login_limiter._buckets.clear()
    yield
    _login_limiter._buckets.clear()


def test_404_template_not_found_localized(en_locale, auth_client):
    r = auth_client.get("/api/v1/templates/does-not-exist", headers={"Accept-Language": "en-US"})
    assert r.status_code == 404
    body = r.json()
    assert body["code"] == "http.template.not_found"
    assert body["detail"] == "Template not found"
    assert r.headers["Content-Language"] == "en-US"


def test_404_template_not_found_zh_cn(auth_client):
    r = auth_client.get("/api/v1/templates/does-not-exist", headers={"Accept-Language": "zh-CN"})
    assert r.status_code == 404
    body = r.json()
    assert body["code"] == "http.template.not_found"
    assert body["detail"] == "模板不存在"
    assert r.headers["Content-Language"] == "zh-CN"


def test_404_template_not_found_zh_tw(auth_client):
    r = auth_client.get("/api/v1/templates/does-not-exist", headers={"Accept-Language": "zh-TW"})
    assert r.status_code == 404
    body = r.json()
    assert body["code"] == "http.template.not_found"
    assert body["detail"] == "範本不存在"
    assert r.headers["Content-Language"] == "zh-TW"


def test_404_interview_not_found_localized(zh_tw_locale, auth_client):
    r = auth_client.get("/api/v1/interviews/nonexistent-id", headers={"Accept-Language": "zh-TW"})
    assert r.status_code == 404
    body = r.json()
    assert body["code"] == "http.session.not_found"
    assert body["detail"] == "會話不存在"
    assert r.headers["Content-Language"] == "zh-TW"


def test_invalid_credentials_localized(zh_cn_locale):
    from app.app import create_app
    c = TestClient(create_app())
    r = c.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "wrong"},
        headers={"Accept-Language": "zh-CN"},
    )
    assert r.status_code == 401
    body = r.json()
    assert body["code"] == "http.auth.invalid_credentials"
    assert body["detail"] == "用户名或密码错误"
    assert r.headers["Content-Language"] == "zh-CN"


def test_rate_limit_zh_tw():
    """Spam 6 rapid logins, last one should be 429 with localized detail."""
    from app.app import create_app
    c = TestClient(create_app())
    for _ in range(5):
        c.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "wrong"},
            headers={"Accept-Language": "zh-TW"},
        )
    r = c.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "wrong"},
        headers={"Accept-Language": "zh-TW"},
    )
    assert r.status_code == 429
    body = r.json()
    assert body["code"] == "http.auth.rate_limited"
    assert body["detail"] == "嘗試過於頻繁，請稍後再試"
