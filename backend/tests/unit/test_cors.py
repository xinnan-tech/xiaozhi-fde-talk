from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.app import _resolve_cors_origins


@dataclass
class FakeSettings:
    cors_origins: str = ""
    env: str = "dev"


def test_resolve_cors_explicit_list():
    s = FakeSettings(cors_origins="https://a.com, https://b.com", env="prod")
    assert _resolve_cors_origins(s) == ["https://a.com", "https://b.com"]


def test_resolve_cors_dev_fallback_default():
    s = FakeSettings(cors_origins="", env="dev")
    origins = _resolve_cors_origins(s)
    assert "http://localhost:5173" in origins


def test_resolve_cors_test_fallback_default():
    s = FakeSettings(cors_origins="", env="test")
    origins = _resolve_cors_origins(s)
    assert "http://localhost:5173" in origins


def test_resolve_cors_prod_unset_raises():
    s = FakeSettings(cors_origins="", env="prod")
    with pytest.raises(RuntimeError, match="CORS_ORIGINS"):
        _resolve_cors_origins(s)


def test_resolve_cors_prod_explicit_allowed():
    s = FakeSettings(cors_origins="https://talk.example.com", env="prod")
    assert _resolve_cors_origins(s) == ["https://talk.example.com"]


def test_resolve_cors_trims_whitespace_and_drops_empty():
    s = FakeSettings(cors_origins=" a.com ,, b.com ,  ", env="dev")
    assert _resolve_cors_origins(s) == ["a.com", "b.com"]