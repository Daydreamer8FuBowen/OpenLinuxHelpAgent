from __future__ import annotations
"""
SQLite 持久化层
职责：
- 建库建表并提供对话、消息、工具调用、用户记忆与 token 统计的读写接口
- 供上层 SqliteHistory 与 App 入口调用
"""

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from LinuxAgent.log import get_logger


logger = get_logger("Memory.sqlite_db")

def _utc_now_iso() -> str:
    """UTC ISO 时间戳，用于记录创建时间。"""
    return datetime.now(tz=timezone.utc).isoformat()


def _default_db_path() -> Path:
    """默认数据库路径；可通过 CHELP_SQLITE_DB 覆盖。"""
    configured = os.getenv("CHELP_SQLITE_DB")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".chelp" / "memory.db"


@dataclass(frozen=True)
class SqlitePaths:
    db_file: Path
    """SQLite 文件路径集合。"""

    @staticmethod
    def load() -> "SqlitePaths":
        """加载默认数据库文件路径。"""
        return SqlitePaths(db_file=_default_db_path())

    def ensure_dirs(self) -> None:
        """确保数据库目录存在。"""
        self.db_file.parent.mkdir(parents=True, exist_ok=True)


class SQLiteMemoryDB:
    """SQLite 工具类：负责连接管理与业务表的读写。"""
    def __init__(self, db_path: str | Path | None = None) -> None:
        self._paths = SqlitePaths(db_file=Path(db_path).expanduser()) if db_path else SqlitePaths.load()
        self._paths.ensure_dirs()
        self._conn = self._connect()
        self.ensure_schema()
        logger.info("db opened path=%s", self._paths.db_file)

    def _connect(self) -> sqlite3.Connection:
        """建立连接并开启 WAL、外键支持。"""
        conn = sqlite3.connect(self._paths.db_file, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        return conn

    @property
    def db_file(self) -> Path:
        """返回数据库文件路径。"""
        return self._paths.db_file

    def close(self) -> None:
        """关闭数据库连接。"""
        try:
            self._conn.close()
        except Exception:
            pass

    def __enter__(self) -> "SQLiteMemoryDB":
        """支持 with 上下文管理。"""
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        """退出上下文时关闭连接。"""
        self.close()

    def ensure_schema(self) -> None:
        """创建所需业务表与索引（如不存在）。"""
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS chat_turns (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              created_at TEXT NOT NULL,
              user_text TEXT NOT NULL,
              agent_text TEXT NOT NULL DEFAULT '',
              model TEXT,
              allow_execute INTEGER
            );

            CREATE TABLE IF NOT EXISTS chat_messages (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              turn_id INTEGER NOT NULL,
              created_at TEXT NOT NULL,
              role TEXT NOT NULL,
              content TEXT NOT NULL,
              message_index INTEGER,
              FOREIGN KEY (turn_id) REFERENCES chat_turns(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_chat_messages_turn_id ON chat_messages(turn_id);
            CREATE INDEX IF NOT EXISTS idx_chat_messages_created_at ON chat_messages(created_at);

            CREATE TABLE IF NOT EXISTS tool_calls (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              turn_id INTEGER NOT NULL,
              created_at TEXT NOT NULL,
              tool_name TEXT NOT NULL,
              command TEXT NOT NULL,
              ok INTEGER,
              exit_code INTEGER,
              stdout TEXT,
              stderr TEXT,
              observation TEXT,
              FOREIGN KEY (turn_id) REFERENCES chat_turns(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_tool_calls_turn_id ON tool_calls(turn_id);
            CREATE INDEX IF NOT EXISTS idx_tool_calls_created_at ON tool_calls(created_at);

            CREATE TABLE IF NOT EXISTS user_memories (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              created_at TEXT NOT NULL,
              tags TEXT NOT NULL DEFAULT '',
              markdown TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_user_memories_created_at ON user_memories(created_at);
            CREATE INDEX IF NOT EXISTS idx_user_memories_tags ON user_memories(tags);

            CREATE TABLE IF NOT EXISTS token_usage (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              turn_id INTEGER NOT NULL UNIQUE,
              created_at TEXT NOT NULL,
              prompt_tokens INTEGER,
              completion_tokens INTEGER,
              total_tokens INTEGER,
              total_cost REAL,
              FOREIGN KEY (turn_id) REFERENCES chat_turns(id) ON DELETE CASCADE
            );
            """
        )
        logger.debug("schema ensured")

    def begin_turn(self, *, user_text: str, model: str | None, allow_execute: bool | None) -> int:
        """创建一轮对话，并写入首条 user 消息。返回 turn_id。"""
        created_at = _utc_now_iso()
        cur = self._conn.execute(
            "INSERT INTO chat_turns(created_at, user_text, model, allow_execute) VALUES (?, ?, ?, ?)",
            (created_at, user_text, model, int(allow_execute) if allow_execute is not None else None),
        )
        turn_id = int(cur.lastrowid)
        self.add_message(turn_id=turn_id, role="user", content=user_text, message_index=0)
        logger.info("turn begin id=%s model=%s allow_execute=%s", turn_id, model, allow_execute)
        return turn_id

    def end_turn(self, *, turn_id: int, agent_text: str) -> None:
        """结束一轮对话，写入 agent 文本并追加 assistant 消息。"""
        self._conn.execute("UPDATE chat_turns SET agent_text=? WHERE id=?", (agent_text, turn_id))
        self.add_message(turn_id=turn_id, role="assistant", content=agent_text, message_index=1)
        logger.info("turn end id=%s", turn_id)

    def add_message(self, *, turn_id: int, role: str, content: str, message_index: int | None = None) -> int:
        """追加一条消息记录，返回 message_id。"""
        created_at = _utc_now_iso()
        cur = self._conn.execute(
            "INSERT INTO chat_messages(turn_id, created_at, role, content, message_index) VALUES (?, ?, ?, ?, ?)",
            (turn_id, created_at, role, content, message_index),
        )
        return int(cur.lastrowid)

    def add_tool_call(
        self,
        *,
        turn_id: int,
        tool_name: str,
        command: str,
        ok: bool | None,
        exit_code: int | None,
        stdout: str | None,
        stderr: str | None,
        observation: str | None,
    ) -> int:
        """记录一次工具调用及其结果，返回记录 id。"""
        created_at = _utc_now_iso()
        cur = self._conn.execute(
            """
            INSERT INTO tool_calls(
              turn_id, created_at, tool_name, command, ok, exit_code, stdout, stderr, observation
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                turn_id,
                created_at,
                tool_name,
                command,
                int(ok) if ok is not None else None,
                exit_code,
                stdout,
                stderr,
                observation,
            ),
        )
        logger.info("tool call saved turn_id=%s tool=%s exit_code=%s ok=%s", turn_id, tool_name, exit_code, ok)
        return int(cur.lastrowid)

    def upsert_token_usage(
        self,
        *,
        turn_id: int,
        prompt_tokens: int | None,
        completion_tokens: int | None,
        total_tokens: int | None,
        total_cost: float | None,
    ) -> None:
        """按 turn_id 插入或更新 token 统计。"""
        created_at = _utc_now_iso()
        self._conn.execute(
            """
            INSERT INTO token_usage(turn_id, created_at, prompt_tokens, completion_tokens, total_tokens, total_cost)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(turn_id) DO UPDATE SET
              created_at=excluded.created_at,
              prompt_tokens=excluded.prompt_tokens,
              completion_tokens=excluded.completion_tokens,
              total_tokens=excluded.total_tokens,
              total_cost=excluded.total_cost
            """,
            (turn_id, created_at, prompt_tokens, completion_tokens, total_tokens, total_cost),
        )
        logger.info("token usage saved turn_id=%s total_tokens=%s", turn_id, total_tokens)

    def add_user_memory(self, *, markdown: str, tags: str) -> int:
        """追加一条用户永久记忆，返回 id。"""
        created_at = _utc_now_iso()
        cur = self._conn.execute(
            "INSERT INTO user_memories(created_at, tags, markdown) VALUES (?, ?, ?)",
            (created_at, tags, markdown),
        )
        logger.info("user memory saved tags=%s", tags)
        return int(cur.lastrowid)

    def search_user_memories(self, *, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """按 tags/markdown 做简单关键字检索，返回最近匹配的记忆。"""
        q = (query or "").strip()
        if not q:
            return []
        like = f"%{q}%"
        rows = self._conn.execute(
            """
            SELECT id, created_at, tags, markdown
            FROM user_memories
            WHERE tags LIKE ? OR markdown LIKE ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (like, like, limit),
        ).fetchall()
        logger.debug("user memories searched query=%s matches=%s", q[:80], len(rows))
        return [dict(r) for r in rows]

    def list_recent_turns(self, *, limit: int = 10) -> list[dict[str, Any]]:
        """查询最近 N 轮对话的概要信息。"""
        rows = self._conn.execute(
            "SELECT id, created_at, user_text, agent_text FROM chat_turns ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def list_recent_tool_calls(self, *, limit: int = 10) -> list[dict[str, Any]]:
        """查询最近 N 次工具调用的概要信息。"""
        rows = self._conn.execute(
            """
            SELECT id, created_at, turn_id, tool_name, command, ok, exit_code
            FROM tool_calls
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def load_recent_messages(self, *, limit_messages: int = 20) -> list[dict[str, Any]]:
        """查询最近 N 条消息（按时间倒序），再反转为正序返回。"""
        rows = self._conn.execute(
            """
            SELECT id, turn_id, created_at, role, content, message_index
            FROM chat_messages
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit_messages,),
        ).fetchall()
        messages = [dict(r) for r in rows]
        messages.reverse()
        return messages

