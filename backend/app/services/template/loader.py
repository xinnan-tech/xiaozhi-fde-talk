"""模板加载 + 内存缓存。

从本地 JSON 加载并缓存。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from app.domain.template import Template

logger = logging.getLogger(__name__)

# 后端服务根（backend/）；数据目录 templates/（复数）
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_TEMPLATES_DIR = _PROJECT_ROOT / "templates"
_cache: dict[str, Template] = {}


def load_templates() -> dict[str, Template]:
    """加载 templates/ 下所有 JSON 模板，缓存后返回。"""
    if _cache:
        return _cache

    if not _TEMPLATES_DIR.exists():
        logger.warning("模板目录不存在：%s", _TEMPLATES_DIR)
        return _cache

    for path in _TEMPLATES_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            tpl = Template(**data)
            _cache[tpl.id] = tpl
            logger.info("已加载模板：%s v%s", tpl.id, tpl.version)
        except Exception as e:  # noqa: BLE001
            logger.error("加载模板失败 %s：%s", path, e)

    return _cache


def get_template(template_id: str) -> Optional[Template]:
    return load_templates().get(template_id)


def list_templates() -> list[Template]:
    return list(load_templates().values())
