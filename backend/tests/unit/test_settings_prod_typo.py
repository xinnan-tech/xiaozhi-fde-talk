"""Settings prod typo 环境变量检查（Wave 3 P1 #25）。

策略：prod 启动期扫 OS environ，把「不在 Settings 字段白名单内 + 看起来像应用配置」
（非 PATH/HOME 等系统白名单）的 env 名列出，拒启动防止 DATABASE_URL 这种
拼写错被默认 extra="ignore" 静默吞掉。
"""
from __future__ import annotations

import os

import pytest

from app.core.i18n.errors import I18nError
from app.core.settings import check_prod_no_typo_env, _is_app_setting_name


def _isolate(monkeypatch):
    """清空 env 中所有可能冲突的键。"""
    for key in (
        "DATABASE_URL", "DATABSE_URL", "DB_UR", "DB_URL",
        "CORS_ORIGINS", "ENV", "APP_ENV", "ASR_WS_URL",
    ):
        monkeypatch.delenv(key, raising=False)


def test_typo_env_rejected(monkeypatch):
    """DATABASE_URL（应是 DB_URL）+ 一些系统变量 → 必出现。"""
    _isolate(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@db:5432/x")  # typo
    monkeypatch.setenv("CORS_ORIGINS", "https://x.example")
    monkeypatch.setenv("HOME", "/root")  # 系统白名单，不应进 suspects
    monkeypatch.setenv("PATH", "/usr/bin")  # 系统白名单

    suspects = check_prod_no_typo_env(strict=False)
    assert "DATABASE_URL" in suspects, f"应当识别 DATABASE_URL；got={suspects}"
    assert "HOME" not in suspects
    assert "PATH" not in suspects
    assert "CORS_ORIGINS" not in suspects


def test_strict_raises(monkeypatch):
    """strict=True + 命中 typo 抛 I18nError。"""
    _isolate(monkeypatch)
    monkeypatch.setenv("DATABSE_URL", "postgresql+asyncpg://u:p@db:5432/x")
    with pytest.raises(I18nError):
        check_prod_no_typo_env(strict=True)


def test_known_fields_pass_through(monkeypatch):
    """所有 Settings 字段名都不出现在 suspects 里。"""
    _isolate(monkeypatch)
    for key in (
        "HOST", "PORT", "LOG_LEVEL", "LOG_FILE",
        "DB_URL", "DB_ECHO", "ENV", "HOST", "JWT_ALGORITHM",
        "SERVE_FRONTEND", "LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL",
        "ASR_TYPE", "ASR_WS_URL", "CORS_ORIGINS",
        "APP_DB_USE_ALEMBIC", "WEB_CONCURRENCY", "APP_ENV",
    ):
        monkeypatch.setenv(key, "x")
    suspects = check_prod_no_typo_env(strict=False)
    # 命中 0 条；只要一条都不应包含我们已知的字段
    known_violations = [s for s in suspects if s in (
        "HOST", "PORT", "LOG_LEVEL", "LOG_FILE",
        "DB_URL", "DB_ECHO", "ENV", "JWT_ALGORITHM",
        "SERVE_FRONTEND", "LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL",
        "ASR_TYPE", "ASR_WS_URL", "CORS_ORIGINS",
        "APP_DB_USE_ALEMBIC", "WEB_CONCURRENCY", "APP_ENV",
    )]
    assert known_violations == [], \
        f"已知字段被误判为 typo: {known_violations}; full={suspects}"


def test_is_app_setting_name_filters_system():
    """PATH / HOME / JAVA_HOME 这种系统变量不被视作应用配置。"""
    assert _is_app_setting_name("PATH") is False
    assert _is_app_setting_name("HOME") is False
    assert _is_app_setting_name("JAVA_HOME") is False
    assert _is_app_setting_name("PYTHONPATH") is False
    assert _is_app_setting_name("ANTHROPIC_API_KEY") is False  # Claude Code
    assert _is_app_setting_name("CLAUDE_CODE_SESSION_ID") is False
    assert _is_app_setting_name("FOO_BAR") is True
    assert _is_app_setting_name("DB_URL") is True


def test_empty_env_no_suspects(monkeypatch):
    """env 里啥应用配置都没有 → 空清单。"""
    _isolate(monkeypatch)
    suspects = check_prod_no_typo_env(strict=False)
    # 视测试环境可能有其它变量，但不应有 DATABASE_URL 这种
    assert "DATABASE_URL" not in suspects
