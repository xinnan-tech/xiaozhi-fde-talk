"""· FunASR 响应解析正则预编译（m-009）。

_recv_loop 每条 ASR 消息都 re.search/re.sub 内联字面量模式，热路径上反复编译
同一正则。提为模块级 _TAG_RE / _STRIP_RE 预编译 Pattern。
"""
from __future__ import annotations

import re

from app.adapters.asr import funasr_server


def test_tag_and_strip_patterns_precompiled():
    tag = getattr(funasr_server, "_TAG_RE", None)
    strip = getattr(funasr_server, "_STRIP_RE", None)
    assert isinstance(tag, re.Pattern), "_TAG_RE 应为模块级预编译 re.Pattern"
    assert isinstance(strip, re.Pattern), "_STRIP_RE 应为模块级预编译 re.Pattern"


def test_strip_pattern_preserves_original_semantics():
    raw = "你好<|happy|>世界"
    assert funasr_server._TAG_RE.search(raw) is not None
    assert funasr_server._STRIP_RE.sub("", raw).strip() == "你好世界"


def test_no_tag_yields_no_match():
    assert funasr_server._TAG_RE.search("普通文本无标签") is None
