from __future__ import annotations


def test_extract_bearer_from_subprotocol():
    """从 Sec-WebSocket-Protocol 列表里找 bearer.<token>。"""
    from app.transport.websocket.handler import _token_from_subprotocols
    assert _token_from_subprotocols(["bearer.abc123"]) == "abc123"
    assert _token_from_subprotocols([]) is None
    assert _token_from_subprotocols(["chat", "bearer.xyz"]) == "xyz"
