"""锁死 src 里 background 图引用的是 webp 不是 png。"""
import re
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[2] / "src"

PNG_BG_REF = re.compile(r'url\(["\']?@/assets/images/bg\.png["\']?\)')


def test_no_bg_png_in_src():
    offenders = []
    for path in SRC_ROOT.rglob("*.vue"):
        text = path.read_text(encoding="utf-8")
        if PNG_BG_REF.search(text):
            offenders.append(path.relative_to(SRC_ROOT.parent))
    assert not offenders, f"以下文件还在引用 bg.png：{offenders}"


def test_bg_webp_exists():
    webp = SRC_ROOT / "assets" / "images" / "bg.webp"
    assert webp.is_file(), f"缺失: {webp}"
    head = webp.read_bytes()[:4]
    assert head == b"RIFF", f"bg.webp 头={head!r}，不是合法 WebP"


def test_bg_webp_is_smaller_than_png():
    webp = (SRC_ROOT / "assets" / "images" / "bg.webp").stat().st_size
    png = (SRC_ROOT / "assets" / "images" / "bg.png").stat().st_size
    assert webp < png * 0.5, (
        f"bg.webp ({webp}B) 没明显小于 bg.png ({png}B)"
    )
