from __future__ import annotations
"""
应用层配置
职责：
- 管理指令白名单的配置文件：读取/写入/增删
"""

import json
import os
from dataclasses import dataclass
import sys
from pathlib import Path
from typing import Iterable

from LinuxAgent.log import get_logger


logger = get_logger("App.config")

def _default_whitelist_path() -> Path:
    configured = os.getenv("CHELP_WHITELIST_FILE")
    if configured:
        return Path(configured).expanduser()
    if sys.platform.startswith("win"):
        base = os.getenv("APPDATA") or os.getenv("LOCALAPPDATA") or str(Path.home())
        return Path(base) / "chelp" / "whitelist.json"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "chelp" / "whitelist.json"
    base = os.getenv("XDG_CONFIG_HOME") or (Path.home() / ".config")
    return Path(base) / "chelp" / "whitelist.json"


@dataclass(frozen=True)
class ConfigPaths:
    whitelist_file: Path

    @staticmethod
    def load() -> "ConfigPaths":
        return ConfigPaths(whitelist_file=_default_whitelist_path())

    def ensure_dirs(self) -> None:
        self.whitelist_file.parent.mkdir(parents=True, exist_ok=True)


def _normalize_cmds(cmds: Iterable[str]) -> list[str]:
    seen = set()
    result: list[str] = []
    for c in cmds or []:
        s = (c or "").strip()
        if not s or s in seen:
            continue
        seen.add(s)
        result.append(s)
    return result


def load_whitelist() -> set[str]:
    paths = ConfigPaths.load()
    if not paths.whitelist_file.exists():
        logger.info("whitelist file missing path=%s", paths.whitelist_file)
        return set()
    try:
        data = json.loads(paths.whitelist_file.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("whitelist"), list):
            items = _normalize_cmds(map(str, data.get("whitelist")))
        elif isinstance(data, list):
            items = _normalize_cmds(map(str, data))
        else:
            items = []
        loaded = set(items)
        logger.info("whitelist loaded path=%s size=%s", paths.whitelist_file, len(loaded))
        return loaded
    except Exception:
        logger.exception("whitelist load failed path=%s", paths.whitelist_file)
        return set()


def save_whitelist(cmds: Iterable[str]) -> None:
    paths = ConfigPaths.load()
    paths.ensure_dirs()
    items = _normalize_cmds(cmds)
    content = json.dumps({"whitelist": items}, ensure_ascii=False, indent=2)
    paths.whitelist_file.write_text(content, encoding="utf-8")
    logger.info("whitelist saved path=%s size=%s", paths.whitelist_file, len(items))


def add_to_whitelist(cmds: Iterable[str]) -> None:
    current = load_whitelist()
    current.update(_normalize_cmds(cmds))
    save_whitelist(sorted(current))


def remove_from_whitelist(cmds: Iterable[str]) -> None:
    current = load_whitelist()
    for c in _normalize_cmds(cmds):
        current.discard(c)
    save_whitelist(sorted(current))
