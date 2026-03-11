from __future__ import annotations

import logging
import os
import sys
from pathlib import Path


_LOGGER_NAME = "LinuxAgent"
_initialized = False


def _default_log_path() -> Path:
    configured = os.getenv("CHELP_LOG_FILE")
    if configured:
        return Path(configured).expanduser()

    if sys.platform.startswith("win"):
        base = os.getenv("LOCALAPPDATA") or os.getenv("APPDATA") or str(Path.home())
        return Path(base) / "chelp" / "chelp.log"

    if sys.platform == "darwin":
        return Path.home() / "Library" / "Logs" / "chelp" / "chelp.log"

    base = os.getenv("XDG_STATE_HOME") or (Path.home() / ".local" / "state")
    return Path(base) / "chelp" / "chelp.log"


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def init_logging() -> logging.Logger:
    global _initialized
    logger = logging.getLogger(_LOGGER_NAME)
    if _initialized:
        return logger

    level_name = (os.getenv("CHELP_LOG_LEVEL") or "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logger.setLevel(level)
    logger.propagate = False

    fmt = logging.Formatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    log_file = _default_log_path()
    try:
        _ensure_parent(log_file)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(fmt)
        logger.addHandler(file_handler)
    except Exception:
        pass

    console_enabled = (os.getenv("CHELP_LOG_CONSOLE") or "1").strip() not in {"0", "false", "False"}
    if console_enabled:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(level)
        console_handler.setFormatter(fmt)
        logger.addHandler(console_handler)

    _initialized = True
    logger.debug("logging initialized")
    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    init_logging()
    if not name:
        return logging.getLogger(_LOGGER_NAME)
    return logging.getLogger(f"{_LOGGER_NAME}.{name}")

