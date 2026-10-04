"""Logging configuration with mandatory redaction on every handler."""

from __future__ import annotations

import logging
import sys
from typing import IO

from app.security.privacy import get_privacy_manager


class RedactingFilter(logging.Filter):
    """Rewrites each record (message, args and traceback) before it is emitted."""

    def filter(self, record: logging.LogRecord) -> bool:
        privacy = get_privacy_manager()
        if isinstance(record.args, tuple) and record.args:
            # Redact each argument but keep the tuple: some formatters (uvicorn access
            # logs) unpack record.args themselves.
            record.args = tuple(
                privacy.sanitize_log(a) if isinstance(a, str) else a for a in record.args
            )
        try:
            message = record.getMessage()
        except Exception:  # malformed args: never let raw args through
            message, record.args = str(record.msg), ()
        clean = privacy.sanitize_log(message)
        if clean != message:
            # Sensitive data only visible once assembled (e.g. "cookie=%s"): collapse.
            record.msg, record.args = clean, ()
        elif not record.args:
            record.msg = clean
        if record.exc_info:
            formatted = logging.Formatter().formatException(record.exc_info)
            record.exc_text = privacy.sanitize_log(formatted)
            record.exc_info = None
        if record.stack_info:
            record.stack_info = privacy.sanitize_log(record.stack_info)
        return True


_FORMAT = "%(asctime)s %(levelname)s %(name)s - %(message)s"


def configure_logging(level: int = logging.INFO, stream: IO[str] | None = None) -> logging.Handler:
    """Install a single redacting handler on the root logger (idempotent)."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, "_air_upgrade", False):
            root.removeHandler(handler)
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(logging.Formatter(_FORMAT))
    handler.addFilter(RedactingFilter())
    handler._air_upgrade = True  # type: ignore[attr-defined]
    root.addHandler(handler)
    root.setLevel(level)
    # Uvicorn installs its own handlers: make them redact too.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        for h in logging.getLogger(name).handlers:
            if not any(isinstance(f, RedactingFilter) for f in h.filters):
                h.addFilter(RedactingFilter())
    return handler
