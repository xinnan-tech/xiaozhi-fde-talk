"""issue #240 round2 P1.2：_client_ip 验 trusted-proxy 防 XFF 伪造。

直连：socket 地址即客户端，永远可信。
经反向代理：socket 是代理地址，必须验 request.client.host 在 trusted_proxies
白名单里、且 XFF 首跳存在，才采用 XFF。攻击者塞伪造 XFF 时 socket 不在白
名单就走 socket 路径，伪造 XFF 被忽略——本 PR 想堵的 IP 池绕过等于没堵。
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.transport.http.routes import auth as auth_route


@pytest.fixture(autouse=True)
def _patch_trusted_proxies(monkeypatch):
    """每个用例设一组受信任代理，monkeypatch 自动还原。

    直接打 settings.trusted_proxies 走 get_settings() 链：避免改了不还原
    影响其他测试。
    """
    from app.core.settings import get_settings

    # 默认给一个常见白名单——10.0.0.1 是虚构反代。
    monkeypatch.setattr(get_settings(), "trusted_proxies", "10.0.0.1,127.0.0.1")


def _make_request(socket_host: str, xff: str | None = None) -> MagicMock:
    request = MagicMock()
    request.client.host = socket_host
    request.headers.get = lambda k: xff if k == "x-forwarded-for" else None
    return request


def test_direct_connection_ignores_xff():
    """socket 不在白名单 → 永远走 socket，不读 XFF。

    公网直接打后端：攻击者塞伪造 XFF 也不会被采信，否则可绕过 IP 桶。
    """
    request = _make_request("203.0.113.7", xff="1.1.1.1")
    assert auth_route._client_ip(request) == "203.0.113.7"


def test_trusted_proxy_with_xff_uses_xff_first_hop():
    """socket 是 trusted proxy + 有 XFF → 用 XFF 首跳。

    真实反代链：客户端 1.1.1.1 → nginx 10.0.0.1 → 后端。XFF 首跳即客户端。
    """
    request = _make_request("10.0.0.1", xff="1.1.1.1, 10.0.0.1")
    assert auth_route._client_ip(request) == "1.1.1.1"


def test_trusted_proxy_without_xff_falls_back_to_socket():
    """socket 是 trusted proxy 但无 XFF 头 → 走 socket 路径。

    防御：反代配置漏 XFF 时别直接信任 socket 当客户端——直接用 socket 是
    反代 IP，所有真实用户共享同一桶。
    """
    request = _make_request("10.0.0.1", xff=None)
    assert auth_route._client_ip(request) == "10.0.0.1"


def test_trusted_proxy_with_only_xff_synthetic_blocks_spoof():
    """socket 不在白名单、伪造 XFF → 取 socket 不取 XFF。

    这就是 P1.2 核心：未配置 trusted_proxy 时，攻击者塞 XFF 也无效。
    """
    request = _make_request("203.0.113.7", xff="1.1.1.1")
    ip = auth_route._client_ip(request)
    assert ip != "1.1.1.1", (
        f"socket 不在 trusted_proxies 白名单时，伪造 XFF 必须被忽略；实得 {ip}"
    )
    assert ip == "203.0.113.7"


def test_empty_trusted_proxies_disables_xff_completely(monkeypatch):
    """settings.trusted_proxies="" → 完全不读 XFF，永远走 socket。

    dev/test 默认空：直连测试不走反向代理，XFF 不该被采信。
    """
    from app.core.settings import get_settings

    monkeypatch.setattr(get_settings(), "trusted_proxies", "")

    request = _make_request("203.0.113.7", xff="1.1.1.1")
    assert auth_route._client_ip(request) == "203.0.113.7"


def test_cidr_in_trusted_proxies_does_not_match_as_literal(monkeypatch):
    """round3 P1.2：CIDR 字符串不进 _client_ip 实现——运维误写 CIDR 时永命中。

    settings 注释说只支持裸 IP：拿 `10.0.0.0/8` 当字面字符串进白名单集合后，
    socket 是 `10.0.0.5` 也不命中——永远走 socket 不读 XFF。
    这是「注释与实现一致」的诚实文档预期：CIDR 会被当字面 IP 字符串读，永远不
    与真实 socket IP 相等；如果需要 CIDR 应该改造 _client_ip 用 ipaddress 库。
    """
    from app.core.settings import get_settings

    monkeypatch.setattr(get_settings(), "trusted_proxies", "10.0.0.0/8")

    # socket 在 CIDR 范围内，但白名单只存了字面字符串 `10.0.0.0/8`——永不命中
    request = _make_request("10.0.0.5", xff="1.1.1.1")
    assert auth_route._client_ip(request) == "10.0.0.5", (
        f"运维误写 CIDR 必须不被当 IP 匹配；实得 {auth_route._client_ip(request)}"
    )
    # 顺便验：真要支持 CIDR 必须走 ipaddress.ip_network，本测试只锁「现在不支持」
