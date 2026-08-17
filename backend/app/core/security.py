"""安全工具：密码哈希 + PII 脱敏。

放在 core/ 而非 persistence/：哈希是安全关注点，不是持久化关注点。
"""
from __future__ import annotations

import asyncio
import hashlib

import bcrypt


# ─────────────── 密码哈希（直接用 bcrypt，不走 passlib 避免 4.x 兼容问题）───────────────

def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


async def hash_password_async(plain: str) -> str:
    return await asyncio.to_thread(hash_password, plain)


async def verify_password_async(plain: str, hashed: str) -> bool:
    return await asyncio.to_thread(verify_password, plain, hashed)


# ─────────────── PII / PHI 脱敏 ───────────────

def redact_text(text: str, max_chars: int = 20) -> str:
    """日志脱敏：只保留前 N 字符 + hash 指纹，防止转写全文落日志违反合规。

    用法：logger.info("transcript: %s", redact_text(seg.text))
    """
    if not text:
        return ""
    preview = text[:max_chars]
    if len(text) <= max_chars:
        return preview
    fingerprint = hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]
    return f"{preview}…[{fingerprint}]"
