"""FunASR 输出归一化：剥离 `<|lang|><|emotion|><|event|><|withitn|>` 标签。

对应 SenseVoice 输出形如：
  `<|zh|><|NEUTRAL|><|Speech|><|withitn|>开饭时间早上9点至下午5点。`
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_TAG_RE = re.compile(r"<\|([^|]+)\|>")
_LANGS = {"zh", "en", "ja", "ko", "yue", "auto"}
_EVENTS = {"Speech", "BGM", "Noise", "Silence"}
_EMOTIONS = {"HAPPY", "SAD", "ANGRY", "NEUTRAL", "FEARFUL", "DISGUSTED", "SURPRISED"}


@dataclass
class NormalizedText:
    text: str = ""
    language: str = ""     # zh / en / ja / ko / yue
    emotion: str = ""      # neutral / happy / ...
    event: str = ""        # speech / bgm / ...


def clean(raw: str) -> NormalizedText:
    """剥标签 → 干净 text + 可选 language/emotion/event 元数据。"""
    if not raw:
        return NormalizedText()
    tags = _TAG_RE.findall(raw)
    text = _TAG_RE.sub("", raw).strip()
    lang = next((t for t in tags if t.lower() in _LANGS), "")
    event = next((t for t in tags if t in _EVENTS), "")
    emotion = next((t for t in tags if t in _EMOTIONS), "")
    return NormalizedText(
        text=text,
        language=lang.lower(),
        emotion=emotion.lower(),
        event=event.lower(),
    )
