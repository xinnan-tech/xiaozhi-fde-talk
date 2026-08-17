"""结构化日志（structlog）。

统一 app 日志 + uvicorn 访问/错误日志为同一渲染格式：
  - 控制台：彩色人类可读（时间 / logger=模块 / 级别 / 消息 + 结构化字段）
  - 文件（可选，LOG_FILE 指定路径）：JSON，便于送 Loki / ES
"""
from __future__ import annotations

import logging
import logging.config
import sys
from pathlib import Path
from typing import Any, Optional

import structlog

_RESET = "\033[0m"
# 级别颜色（对齐 structlog 默认：info=绿 warn=黄 error=红 debug=蓝）
_LEVEL_COLOR = {
    "debug": "\033[34m",
    "info": "\033[32m",
    "warning": "\033[33m",
    "warn": "\033[33m",
    "error": "\033[31m",
    "critical": "\033[1;31m",
}


def _console_renderer(logger, name, event_dict):  # noqa: ANN001
    """紧凑版控制台渲染：保持 structlog 版式，级别用自然宽度（[info]/[debug]/[warning]）。

    structlog 默认 ConsoleRenderer 会把级别补齐到 critical 长度，导致 [info     ] 一片空白；
    这里去掉补齐，各级别按自身宽度显示。
    版式：时间 [级别] 消息 [模块]  key=value
    """
    ts = event_dict.get("timestamp", "")
    level = str(event_dict.get("level", "")).lower()
    event = event_dict.get("event", "")
    logger_name = event_dict.get("logger") or event_dict.get("logger_name") or ""
    exc = event_dict.pop("exception", None)  # format_exc_info 处理后的栈
    extra = {
        k: v for k, v in event_dict.items()
        if k not in ("timestamp", "level", "logger", "logger_name", "event")
    }

    lvl = level
    if sys.stderr.isatty():
        color = _LEVEL_COLOR.get(level)
        if color:
            lvl = f"{color}{lvl}{_RESET}"

    parts = []
    if ts:
        parts.append(str(ts))
    parts.append(f"[{lvl}]")
    parts.append(str(event))
    if logger_name:
        parts.append(f"[{logger_name}]")
    line = " ".join(parts)
    for k, v in extra.items():
        line += f" {k}={v}"
    if exc:
        line += f"\n{exc}"
    return line


def _shared_processors(
    timestamper: structlog.processors.TimeStamper,
) -> list[Any]:
    """渲染前公共处理链：对 structlog 与 stdlib（uvicorn）记录都生效。"""
    return [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,      # 模块名 → logger=xxx（定位用）
        structlog.stdlib.add_log_level,
        timestamper,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]


def configure_logging(
    log_level: str = "INFO",
    log_file: Optional[str] = None,
) -> dict[str, Any]:
    """配置 structlog + stdlib，返回 dictConfig（供 uvicorn 复用，统一格式）。"""
    level = getattr(logging, log_level.upper(), logging.INFO)
    # utc=False：跟随服务器系统时区（英国→UTC，中国→北京时间；读 OS 时区，不写死）
    timestamper = structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S", utc=False)
    shared = _shared_processors(timestamper)

    # structlog 原生 logger（未来模块可用 structlog.get_logger()）的链路
    structlog.configure(
        processors=shared + [structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(level),
        cache_logger_on_first_use=True,
    )

    # 控制台：彩色
    console_formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            _console_renderer,
        ],
    )

    formatters: dict[str, Any] = {
        "console": {"()": lambda: console_formatter},
    }
    handlers: dict[str, Any] = {
        "console": {
            "class": "logging.StreamHandler",
            "stream": sys.stderr,
            "formatter": "console",
        },
    }
    root_handlers = ["console"]

    # 文件：JSON（可选）
    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        json_formatter = structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.processors.JSONRenderer(),
            ],
        )
        formatters["json"] = {"()": lambda: json_formatter}
        handlers["file"] = {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": log_file,
            "maxBytes": 10 * 1024 * 1024,
            "backupCount": 5,
            "encoding": "utf-8",
            "formatter": "json",
        }
        root_handlers.append("file")

    config_dict: dict[str, Any] = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": formatters,
        "handlers": handlers,
        "loggers": {
            # uvicorn 访问 / 错误日志并进同一套渲染器 —— 解决"两套日志"问题
            "uvicorn": {"handlers": root_handlers, "level": log_level, "propagate": False},
            "uvicorn.access": {"handlers": root_handlers, "level": log_level, "propagate": False},
            "uvicorn.error": {"handlers": root_handlers, "level": log_level, "propagate": False},
        },
        "root": {"handlers": root_handlers, "level": log_level},
    }

    logging.config.dictConfig(config_dict)
    return config_dict
