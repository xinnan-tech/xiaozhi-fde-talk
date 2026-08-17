"""WebMDecoder 增量解码：每簇只解一次、解完即丢、_buf 有界。

每簇只解一次、解完即丢，_buf 始终 ≈ 头 + 一个正在填的簇，不累积历史，
结构上不会重发整段音频。
"""
from __future__ import annotations

from app.adapters.asr.audio_decode import WebMDecoder, _CLUSTER_ID

HDR = b"EBML_HEAD+TRACKS"                  # 假头（内部不含簇标记字节）


def _cluster(body: bytes) -> bytes:
    return _CLUSTER_ID + body


def test_waits_until_first_cluster_boundary():
    """只有头、无簇标记：头尚未定位，不解码。"""
    dec = WebMDecoder(min_decode_bytes=4)
    dec._decode = lambda d: b"\x00\x00"
    assert dec.feed(HDR + b"no-cluster-here") == b""
    assert dec._header is None


def test_decodes_only_complete_clusters_keeps_filling_one():
    """头 + C1 + C2(部分)：解「头 + C1」，保留「头 + C2」。C2 不在本轮解。"""
    dec = WebMDecoder(min_decode_bytes=4)
    seen: list[bytes] = []
    dec._decode = lambda d: seen.append(bytes(d)) or b"\x00\x00"
    out = dec.feed(HDR + _cluster(b"C1-body") + _cluster(b"C2-partial"))
    assert out == b"\x00\x00"
    assert seen == [HDR + _cluster(b"C1-body")]
    assert bytes(dec._buf) == HDR + _cluster(b"C2-partial")


def test_each_cluster_decoded_exactly_once():
    """连续喂 C1..C4：每个簇只进 _decode 一次，绝不重解（幽灵转写的根因）。

    每簇解完即丢，绝不重解。
    """
    dec = WebMDecoder(min_decode_bytes=4)
    seen: list[bytes] = []
    dec._decode = lambda d: seen.append(bytes(d)) or b""
    dec.feed(HDR + _cluster(b"A") + _cluster(b"B"))   # 解 A，留 B
    dec.feed(_cluster(b"C"))                          # 解 B，留 C
    dec.feed(_cluster(b"D"))                          # 解 C，留 D
    bodies = [s[len(HDR) + len(_CLUSTER_ID):] for s in seen]
    assert bodies == [b"A", b"B", b"C"]               # D 仍在 _buf 待解
    assert bodies.count(b"A") == 1                    # 每个簇只出现一次
    assert bytes(dec._buf) == HDR + _cluster(b"D")


def test_buffer_stays_bounded_across_many_clusters():
    """喂入大量簇后 _buf 仍 ≈ 头 + 一个簇，不累积。"""
    dec = WebMDecoder(min_decode_bytes=4)
    dec._decode = lambda d: b""
    dec.feed(HDR + _cluster(b"x" * 50))               # 建头 + 第一个正在填的簇
    for _ in range(200):
        dec.feed(_cluster(b"x" * 50))
    assert len(dec._buf) < len(HDR) + 120             # 远小于 200 簇 × 54 字节


def test_throttle_until_min_bytes():
    """min_decode_bytes 节流：待解区不足时不解，攒够才解。"""
    dec = WebMDecoder(min_decode_bytes=1000)
    calls: list[int] = []
    dec._decode = lambda d: calls.append(1) or b""
    dec.feed(HDR + _cluster(b"x" * 10) + _cluster(b"y"))   # 待解区 14B < 1000 → 不解
    assert calls == []
    dec.feed(_cluster(b"z" * 1200) + _cluster(b"w"))       # 待解区超阈值 → 解
    assert len(calls) == 1


def test_force_flush_decodes_remaining_and_resets():
    """force=True（listen:stop/end 刷尾）：把残留（含正在填的簇）整段解一次，复位到头。"""
    dec = WebMDecoder(min_decode_bytes=4)
    seen: list[bytes] = []
    dec._decode = lambda d: seen.append(bytes(d)) or b"\x00\x00"
    dec.feed(HDR + _cluster(b"C1"))                   # 只 1 个簇边界，正常不解
    assert seen == []
    out = dec.feed(b"", force=True)
    assert out == b"\x00\x00"
    assert seen == [HDR + _cluster(b"C1")]
    assert bytes(dec._buf) == HDR                     # 复位到头


def test_safety_valve_on_abnormal_input_without_cluster():
    """迟迟无簇边界（异常输入）：超过 max_buf_bytes 触发安全阀，_buf 复位不爆，置 overflowed。"""
    dec = WebMDecoder(max_buf_bytes=4000, min_decode_bytes=4)
    dec._decode = lambda d: b""
    out = dec.feed(b"\x1a\x45\xdf\xa3" + b"\x00" * 1_000_000)   # EBML 头起手但无簇标记
    assert isinstance(out, bytes)
    assert len(dec._buf) < 1_000_000                  # 安全阀已复位
    assert dec.overflowed is True                     # 异常输入可见


def test_reset_clears_buffer_and_header_for_new_stream():
    """reset 清空缓冲与已缓存的头：listen_start 时调用，等下一条带头的新流。

    前端 recorder 发的续流不含 EBML 头，若 decoder 沿用上一条流缓存的（可能已
    失效的）头，会永久解不出 PCM。reset 让 decoder 重新定位新流的头。
    """
    dec = WebMDecoder(min_decode_bytes=4)
    dec._decode = lambda d: b"\x00\x00"
    dec.feed(HDR + _cluster(b"C1"))           # 建头 + 填充 _buf
    assert dec._header == HDR
    assert len(dec._buf) > 0

    dec.reset()
    assert dec._header is None
    assert bytes(dec._buf) == b""
    assert dec.overflowed is False

    # reset 后能重新定位新流的头
    seen: list[bytes] = []
    dec._decode = lambda d: seen.append(bytes(d)) or b"\x00\x00"
    dec.feed(HDR + _cluster(b"new-C1") + _cluster(b"new-C2"))
    assert dec._header == HDR                  # 重新定位了新流的头
