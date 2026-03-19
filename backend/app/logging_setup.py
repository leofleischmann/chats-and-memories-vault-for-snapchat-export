"""Central logging setup for optional file logging.

Enable via env vars:
  LOG_TO_FILES=1 (or true/yes/on) to enable writing logs to LOG_DIR (default: /logs)
  LOG_LEVEL=DEBUG|INFO|... (default: DEBUG when LOG_TO_FILES enabled)
  LOG_CONSOLE_LEVEL=INFO (default) to control console verbosity
"""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler


def _env_truthy(name: str) -> bool:
    v = os.getenv(name, "").strip().lower()
    return v in ("1", "true", "yes", "y", "on")


def setup_logging() -> None:
    """
    If LOG_TO_FILES is enabled, configure the root logger with:
    - console handler (default INFO)
    - rotating file handler writing DEBUG+ logs to LOG_DIR
    """
    if not _env_truthy("LOG_TO_FILES"):
        return

    log_dir = os.getenv("LOG_DIR", "/logs")
    log_file_name = os.getenv("LOG_FILE_NAME", "snapchats.log")
    log_path = os.path.join(log_dir, log_file_name)

    os.makedirs(log_dir, exist_ok=True)

    root = logging.getLogger()

    # Respect LOG_LEVEL for file logging as well.
    # Otherwise even if LOG_LEVEL=INFO, the file handler would still receive DEBUG logs.
    file_level = getattr(logging, os.getenv("LOG_LEVEL", "DEBUG").upper(), logging.DEBUG)
    console_level = getattr(logging, os.getenv("LOG_CONSOLE_LEVEL", "INFO").upper(), logging.INFO)
    root_level = getattr(logging, os.getenv("LOG_LEVEL", "DEBUG").upper(), logging.DEBUG)
    root.setLevel(root_level)

    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Avoid attaching duplicate handlers if the app reloads.
    already_has_file = any(getattr(h, "snapchats_file_logging", False) for h in root.handlers)
    already_has_console = any(getattr(h, "snapchats_console_logging", False) for h in root.handlers)

    if not already_has_console:
        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(console_level)
        ch.setFormatter(formatter)
        setattr(ch, "snapchats_console_logging", True)
        root.addHandler(ch)

    if not already_has_file:
        max_bytes = int(os.getenv("LOG_MAX_BYTES", str(50 * 1024 * 1024)))  # 50MB
        backup_count = int(os.getenv("LOG_BACKUP_COUNT", "5"))
        fh = RotatingFileHandler(
            log_path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        fh.setLevel(file_level)
        fh.setFormatter(formatter)
        setattr(fh, "snapchats_file_logging", True)
        root.addHandler(fh)

    # Ensure uvicorn logs are not silenced.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.setLevel(logging.INFO)
        lg.propagate = True

    logging.captureWarnings(True)

