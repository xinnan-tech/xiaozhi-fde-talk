# tests/unit/test_llm_i18n.py
import pytest
from app.adapters.llm.openai_compatible import LLMError
from app.core.i18n.messages import Keys


def test_llm_error_alias_resolves_to_correct_key():
    with pytest.raises(LLMError) as ei:
        raise LLMError(Keys.LLM_NO_JSON_BLOCK, http_status=502, snippet="oops")
    assert ei.value.code == "llm.no_json_block"
    assert ei.value.params["snippet"] == "oops"
    assert ei.value.http_status == 502


def test_exception_handler_translates_detail():
    """End-to-end: a 502 raised in a route should translate to localized detail."""
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    from app.core.i18n.context import force_locale, reset_locale
    from app.core.i18n.errors import I18nError
    from fastapi.responses import JSONResponse

    a = FastAPI()

    @a.exception_handler(I18nError)
    async def _h(req, exc: I18nError):
        from app.core.i18n.context import current_locale
        locale = current_locale()
        return JSONResponse(
            status_code=exc.http_status,
            content={"detail": exc.localized(locale=locale), "code": exc.code},
            headers={"Content-Language": locale},
        )

    @a.get("/probe")
    def _probe():
        raise LLMError(Keys.LLM_NO_JSON_BLOCK, http_status=502, snippet="partial response")

    # Mock app context so current_locale can be set independently.
    from app.core.i18n.middleware import I18nHTTPMiddleware
    a.add_middleware(I18nHTTPMiddleware)

    for lang, expected_substr in [
        ("en-US", "LLM returned no JSON block"),
        ("zh-CN", "LLM"),
    ]:
        c = TestClient(a)
        r = c.get("/probe", headers={"Accept-Language": lang})
        assert r.status_code == 502
        body = r.json()
        assert body["code"] == "llm.no_json_block"
        assert expected_substr in body["detail"], (
            f"{lang}: {expected_substr!r} not in {body['detail']!r}"
        )
