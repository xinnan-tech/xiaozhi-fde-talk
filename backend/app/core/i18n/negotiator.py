from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LocaleNegotiation:
    locale: str
    requested: str | None
    q: float


def normalize_locale_tag(tag: str) -> str | None:
    raw = (tag or "").strip()
    if not raw or "," in raw or ";" in raw:
        return None
    for sep in ("-", "_"):
        if sep in raw:
            lang, region = raw.split(sep, 1)
            return f"{lang.lower()}-{region.upper()}"
    return raw.lower()


def resolve_locale(*candidates: str | None) -> str:
    """First non-empty candidate supported by SUPPORTED, else DEFAULT."""
    from .locales import DEFAULT, SUPPORTED
    for c in candidates:
        if not c:
            continue
        norm = normalize_locale_tag(c)
        if norm and norm in SUPPORTED:
            return norm
        # Language fallback: e.g. "zh-SG" → first supported "zh-*" = "zh-CN"
        if norm:
            lang = norm.split("-", 1)[0]
            for s in sorted(SUPPORTED):
                if s == lang or s.startswith(lang + "-"):
                    return s
    return DEFAULT


def parse_accept_language(header: str | None, *, supported: set[str], default: str) -> LocaleNegotiation:
    if not header:
        return LocaleNegotiation(locale=default, requested=None, q=0.0)

    candidates: list[tuple[str, float]] = []
    for raw in header.split(","):
        raw = raw.strip()
        if not raw:
            continue
        q = 1.0
        if ";" in raw:
            tag_part, *params = [p.strip() for p in raw.split(";")]
            for p in params:
                if p.startswith("q="):
                    try:
                        q = float(p[2:])
                    except ValueError:
                        q = 1.0
            tag = tag_part
        else:
            tag = raw
        if tag == "*":
            tag = default
            q = 0.001
        candidates.append((tag, q))

    # Sort by q descending; stable ordering of same-q preserves wire order
    candidates.sort(key=lambda c: c[1], reverse=True)

    for tag, q in candidates:
        if q <= 0:
            continue
        norm = normalize_locale_tag(tag)
        if norm and norm in supported:
            return LocaleNegotiation(locale=norm, requested=tag, q=q)
        if norm:
            lang = norm.split("-", 1)[0]
            for s in sorted(supported):
                if s == lang or s.startswith(lang + "-"):
                    return LocaleNegotiation(locale=s, requested=tag, q=q)
    return LocaleNegotiation(locale=default, requested=None, q=0.0)
