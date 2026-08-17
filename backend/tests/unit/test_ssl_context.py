from __future__ import annotations
import ssl
from app.adapters.asr import funasr_server as f


def test_build_ssl_local_disables_verify():
    ctx = f._build_ssl_context("wss://localhost:10096")
    assert ctx.check_hostname is False
    assert ctx.verify_mode == ssl.CERT_NONE


def test_build_ssl_remote_enforces_verify():
    ctx = f._build_ssl_context("wss://asr.example.com:10096")
    assert ctx.check_hostname is True
    assert ctx.verify_mode == ssl.CERT_REQUIRED


def test_no_module_level_ssl_constant():
    # 模块级 _SSL 必须已删除（不再对所有连接禁验证）
    assert not hasattr(f, "_SSL")
