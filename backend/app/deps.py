"""Shared dependencies for FastAPI routes and services."""
from __future__ import annotations

import logging
import sys
from typing import Any

from app.config import settings


class JsonFormatter(logging.Formatter):
    """Compact JSON log formatter."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        for key, value in record.__dict__.items():
            if key.startswith("ctx_"):
                payload[key[4:]] = value
        # ensure JSON serializable string output
        import json

        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging() -> None:
    """Install a JSON formatter on the root logger once."""
    root = logging.getLogger()
    if getattr(root, "_kp_configured", False):
        return
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.handlers = [handler]
    root.setLevel(getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))
    root._kp_configured = True  # type: ignore[attr-defined]


def get_logger(name: str) -> logging.Logger:
    configure_logging()
    return logging.getLogger(name)
