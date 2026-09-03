"""WebM/EBML（Opus）→ 16k 单声道 int16 PCM。

客户端 MediaRecorder 吐一条连续 WebM 流：首个分片含 EBML 头 + 初始簇，
之后只有簇（无新头）。本解码器「每簇只解一次」：定位首簇、缓存其之前的头；
攒够完整簇后解一次（头 + 若干完整簇）、解完即丢，`_buf` 始终 ≈ 头 + 一个
正在填充的簇——有界内存、O(每簇) 解码、不累积历史。故「缓冲触顶 / 整段历史
重发（幽灵转写）」在结构上不会发生。

PyAV 的 av.open(BytesIO(...)) 只能整段解一次、无原生「追加续解」，故用簇边界
（Matroska Cluster 元素 ID 0x1F43B675）切分：每次解码「头 + 最后一个簇之前
的全部」，把最后一个（正在填）簇原样保留到下一轮——既保证每簇只解一次，
又不割裂跨包的簇。
"""
from __future__ import annotations

import io
import logging

import av
import numpy as np

logger = logging.getLogger(__name__)

_CLUSTER_ID = b"\x1f\x43\xb6\x75"          # Matroska/WebM Cluster 元素 ID
_MIN_DECODE_BYTES = 4000                     # ~1s Opus；攒够完整簇再解，避免每帧小窗冷启动
_DEFAULT_MAX_BUF_BYTES = 1 * 1024 * 1024     # 安全上限：异常输入（迟迟无簇边界）下兜底，正常远不至此


class WebMDecoder:
    def __init__(
        self,
        max_buf_bytes: int = _DEFAULT_MAX_BUF_BYTES,
        min_decode_bytes: int = _MIN_DECODE_BYTES,
    ) -> None:
        self._buf = bytearray()
        self._header: bytes | None = None    # 首簇之前的不变前缀（EBML+Segment+Tracks），一次性缓存
        self._max_buf_bytes = max_buf_bytes
        self._min_decode_bytes = min_decode_bytes
        self.overflowed = False              # 仅安全阀（异常输入）触发；正常路径恒 False

    def reset(self) -> None:
        """清空缓冲与已缓存的头，回到初始态等待一条新的完整流（含 EBML 头）。

        listen_start 时调用：前端每次开始监听都重建 MediaRecorder 发一条带头
        的新流，解码器重新定位头，避免被上一条流的残留/无效头卡死。
        """
        self._buf = bytearray()
        self._header = None
        self.overflowed = False

    def feed(self, webm_bytes: bytes, force: bool = False) -> bytes:
        """追加 WebM 字节，返回本批新解出的 PCM（int16 16k mono bytes）。

        force=True（listen:stop / end 刷尾）：把当前残留整段解一次并复位到头。
        """
        self._buf.extend(webm_bytes)
        if not self._buf:
            return b""

        # 安全阀：异常输入（迟迟无簇边界，或单簇超大）下防止 _buf 无界增长。
        # 正常 MediaRecorder 流簇边界密集，恒不触发；触发即说明输入异常，置 overflowed 供观测。
        if len(self._buf) > self._max_buf_bytes:
            pcm = self._decode(bytes(self._buf))
            self._reset_to_header()
            self.overflowed = True
            return pcm

        # 首次：定位第一个簇边界，缓存其之前的头
        if self._header is None:
            idx = self._buf.find(_CLUSTER_ID)
            if idx < 0:
                return b""                   # 头/首簇尚未到齐，等
            self._header = bytes(self._buf[:idx])

        header = self._header
        tail_start = len(header)
        cluster_offsets = _find_clusters(self._buf, tail_start)
        logger.info(
            "WebM 结构：buffer_bytes=%d header_bytes=%d clusters=%d force=%s",
            len(self._buf),
            len(header),
            len(cluster_offsets),
            force,
        )

        if force:
            pcm = self._decode(bytes(self._buf))
            self._reset_to_header()
            return pcm

        # 至少 2 个簇边界：第 1 个簇才「完整」（延伸到第 2 个簇开始处）。
        if len(cluster_offsets) < 2:
            return b""
        last = cluster_offsets[-1]
        # 节流：待解的完整簇字节不足时等更多（减少频繁小窗解码的冷启动损耗）
        if last - tail_start < self._min_decode_bytes:
            return b""
        # 解「头 + 最后一个簇之前的全部（若干完整簇）」，原样保留最后一个（正在填）簇
        pcm = self._decode(bytes(self._buf[:last]))
        tail = bytes(self._buf[last:])
        self._buf = bytearray(header) + bytearray(tail)
        return pcm

    def _reset_to_header(self) -> None:
        """复位 _buf 到头（丢弃所有簇）；无头则清空。"""
        self._buf = bytearray(self._header) if self._header else bytearray()

    def _decode(self, data: bytes) -> bytes:
        """解码「头 + 若干簇」→ 16k s16 mono PCM bytes。失败/无帧返回 b""。"""
        if not data:
            return b""
        try:
            container = av.open(io.BytesIO(data))
        except Exception:
            return b""
        resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
        frames: list[np.ndarray] = []
        try:
            for f in container.decode(audio=0):
                for rf in resampler.resample(f):
                    frames.append(rf.to_ndarray().reshape(-1))
            for rf in resampler.resample(None):   # flush
                frames.append(rf.to_ndarray().reshape(-1))
        except Exception as exc:
            # 解码中途失败（WebM 不完整/损坏）→ 跳过本批，等更多字节，绝不抛出
            logger.warning(
                "WebM 解码失败：bytes=%d error=%r",
                len(data),
                exc,
            )
            frames = []
        finally:
            container.close()
        if not frames:
            return b""
        return np.concatenate(frames).astype(np.int16).tobytes()


def _find_clusters(buf: bytearray, start: int) -> list[int]:
    """从 start 起扫描所有 Cluster 元素 ID 出现位置（升序）。"""
    offsets: list[int] = []
    i = start
    while True:
        j = buf.find(_CLUSTER_ID, i)
        if j < 0:
            break
        offsets.append(j)
        i = j + len(_CLUSTER_ID)
    return offsets
