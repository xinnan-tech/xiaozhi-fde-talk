from __future__ import annotations


def test_extract_bearer_from_subprotocol():
    """从 Sec-WebSocket-Protocol 列表里找 bearer.<token>。"""
    from app.transport.base import token_from_subprotocols
    assert token_from_subprotocols(["bearer.abc123"]) == "abc123"
    assert token_from_subprotocols([]) is None
    assert token_from_subprotocols(["chat", "bearer.xyz"]) == "xyz"
