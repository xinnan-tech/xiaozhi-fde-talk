"""OCR factory 双组独立 + 配置读 / invalidate 行为。

覆盖:
- get_general_ocr / get_handwriting_ocr 返回独立单例(各自 access_token 缓存)
- invalidate 收到 ocr.* 变更时只清通用单例,不影响手写单例
- invalidate 收到 handwriting.* 变更时只清手写单例,不影响通用单例
- language 字段按组覆盖(通用 OCR 默认 CHN_ENG / 手写 OCR 默认 auto_detect)
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.adapters.ocr import factory
from app.core.config_store import DEFAULTS


@pytest.fixture(autouse=True)
def _reset_factory_singletons():
    """每个用例前后清掉双组单例,避免上一次 mock 残留影响下次构造。"""
    factory._general_provider = None
    factory._handwriting_provider = None
    yield
    factory._general_provider = None
    factory._handwriting_provider = None


def _cfg(**overrides):
    """生成测试用配置字典,未指定的取 DEFAULTS。"""
    base = {
        "ocr.type": "baidu",
        "ocr.base_url": "https://aip.baidubce.com",
        "ocr.api_key": "ak",
        "ocr.secret_key": "sk",
        "ocr.model": "general_basic",
        "ocr.language": "CHN_ENG",
        "handwriting.type": "baidu",
        "handwriting.base_url": "https://aip.baidubce.com",
        "handwriting.api_key": "ak-hw",
        "handwriting.secret_key": "sk-hw",
        "handwriting.model": "handwriting",
        "handwriting.language": "auto_detect",
    }
    base.update(overrides)
    return base


def _patch_config(values: dict[str, str]):
    """patch ConfigStore.get_sync 让 _read_*_config 读到 values。"""

    class _StubStore:
        def get_sync(self, key, default=""):
            return values.get(key, default)

    return patch.object(factory, "get_config_store", _StubStore)


def test_get_general_ocr_returns_baidu_with_general_language():
    """通用 OCR factory 用 ocr.language 默认值(CHN_ENG)传 language。"""
    with _patch_config(_cfg()):
        provider = factory.get_general_ocr()
    assert provider._language == "CHN_ENG"
    assert provider._api_key == "ak"
    assert provider._secret_key == "sk"
    assert provider._model == "general_basic"


def test_get_handwriting_ocr_returns_baidu_with_auto_detect():
    """手写 OCR factory 用 handwriting.language 默认值(auto_detect)。"""
    with _patch_config(_cfg()):
        provider = factory.get_handwriting_ocr()
    assert provider._language == "auto_detect"
    assert provider._api_key == "ak-hw"
    assert provider._secret_key == "sk-hw"
    assert provider._model == "handwriting"


def test_factory_returns_distinct_singletons():
    """两组 OCR 厂独立——access_token 缓存不会冲突(两 group 配置不同)。"""
    with _patch_config(_cfg()):
        gen = factory.get_general_ocr()
        hw = factory.get_handwriting_ocr()
    # 不同实例:独立 access_token 缓存
    assert gen is not hw
    assert gen._api_key == "ak"
    assert hw._api_key == "ak-hw"


def test_factory_caches_per_group():
    """同组多次 get_*() 返回同一单例——B 类配置已 warm,无需重复构造。"""
    with _patch_config(_cfg()):
        gen1 = factory.get_general_ocr()
        gen2 = factory.get_general_ocr()
        hw1 = factory.get_handwriting_ocr()
        hw2 = factory.get_handwriting_ocr()
    assert gen1 is gen2
    assert hw1 is hw2


def test_invalidate_clears_only_general_on_ocr_change():
    """invalidate 收到 ocr.* 变更时只清通用单例。"""
    with _patch_config(_cfg()):
        gen_before = factory.get_general_ocr()
        hw_before = factory.get_handwriting_ocr()

    # 触发 ocr.* 变更
    factory.invalidate({"ocr.type"})

    with _patch_config(_cfg()):
        gen_after = factory.get_general_ocr()
        hw_after = factory.get_handwriting_ocr()

    # 通用组重建,手写组复用
    assert gen_after is not gen_before
    assert hw_after is hw_before


def test_invalidate_clears_only_handwriting_on_handwriting_change():
    """invalidate 收到 handwriting.* 变更时只清手写单例。"""
    with _patch_config(_cfg()):
        gen_before = factory.get_general_ocr()
        hw_before = factory.get_handwriting_ocr()

    # 触发 handwriting.* 变更
    factory.invalidate({"handwriting.api_key"})

    with _patch_config(_cfg()):
        gen_after = factory.get_general_ocr()
        hw_after = factory.get_handwriting_ocr()

    assert gen_after is gen_before
    assert hw_after is not hw_before


def test_invalidate_other_keys_does_not_clear():
    """invalidate 收到与 OCR 无关的 key 变更时不清任何单例。"""
    with _patch_config(_cfg()):
        gen_before = factory.get_general_ocr()
        hw_before = factory.get_handwriting_ocr()

    factory.invalidate({"llm.api_key", "asr.type", "session.idle_timeout_s"})

    with _patch_config(_cfg()):
        gen_after = factory.get_general_ocr()
        hw_after = factory.get_handwriting_ocr()

    assert gen_after is gen_before
    assert hw_after is hw_before


def test_language_overrides_passed_through_factory():
    """admin 改 ocr.language 后,下次 get_general_ocr() 用新值。"""
    # 首次构造用 CHN_ENG
    with _patch_config(_cfg()):
        p1 = factory.get_general_ocr()
    assert p1._language == "CHN_ENG"

    # invalidate + 改 lang
    factory.invalidate({"ocr.language"})
    with _patch_config(_cfg(**{"ocr.language": "ENG"})):
        p2 = factory.get_general_ocr()
    assert p2._language == "ENG"