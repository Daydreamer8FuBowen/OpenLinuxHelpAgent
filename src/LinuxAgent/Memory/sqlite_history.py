from __future__ import annotations
"""
面向业务的历史接口（基于 SQLite）
职责：
- 为 Agent/App 提供读取聊天历史消息、保存一轮对话、列工具调用与对话概要的能力
"""

from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from LinuxAgent.Memory.sqlite_db import SQLiteMemoryDB


def _parse_observation(observation: str | None) -> tuple[int | None, str | None, str | None]:
    """从工具观察文本中拆解 exit_code/stdout/stderr。"""
    if not observation:
        return None, None, None
    lines = observation.splitlines()
    exit_code = None
    stdout = None
    stderr = None
    if lines and lines[0].startswith("exit_code="):
        _, _, code_str = lines[0].partition("=")
        try:
            exit_code = int(code_str.strip())
        except Exception:
            exit_code = None

    def _extract_block(header: str) -> str | None:
        try:
            idx = lines.index(header)
        except ValueError:
            return None
        collected: list[str] = []
        for line in lines[idx + 1 :]:
            if line == "stdout:" or line == "stderr:":
                break
            collected.append(line)
        text = "\n".join(collected).strip()
        return text if text else None

    stdout = _extract_block("stdout:")
    stderr = _extract_block("stderr:")
    return exit_code, stdout, stderr


class SqliteHistory:
    """SQLite 历史管理：组合 DB 工具并提供高层便捷方法。"""
    def __init__(self, db: SQLiteMemoryDB | None = None) -> None:
        self._db = db or SQLiteMemoryDB()

    @property
    def db(self) -> SQLiteMemoryDB:
        return self._db

    def close(self) -> None:
        self._db.close()

    def load_chat_history_messages(self, *, limit_messages: int = 20) -> list[BaseMessage]:
        """加载最近消息并转换为 LangChain 消息对象列表。"""
        rows = self._db.load_recent_messages(limit_messages=limit_messages)
        messages: list[BaseMessage] = []
        for r in rows:
            role = r.get("role")
            content = r.get("content") or ""
            if role == "user":
                messages.append(HumanMessage(content=content))
            elif role == "assistant":
                messages.append(AIMessage(content=content))
        return messages

    def save_turn(
        self,
        *,
        user_text: str,
        assistant_text: str,
        tool_steps: list[Any] | None,
        token_stats: dict[str, Any] | None,
        model: str | None,
        allow_execute: bool | None,
    ) -> int:
        """保存一轮对话与工具调用与 token 统计，返回 turn_id。"""
        turn_id = self._db.begin_turn(user_text=user_text, model=model, allow_execute=allow_execute)
        self._db.end_turn(turn_id=turn_id, agent_text=assistant_text)

        for step in tool_steps or []:
            try:
                action, observation = step
                tool_name = getattr(action, "tool", None) or "tool"
                tool_input = getattr(action, "tool_input", None)
                if isinstance(tool_input, dict):
                    command = tool_input.get("command") or tool_input.get("input") or str(tool_input)
                else:
                    command = str(tool_input) if tool_input is not None else ""

                obs_text = observation if isinstance(observation, str) else str(observation)
                exit_code, stdout, stderr = _parse_observation(obs_text)
                ok = None if exit_code is None else (exit_code == 0)

                self._db.add_tool_call(
                    turn_id=turn_id,
                    tool_name=tool_name,
                    command=command,
                    ok=ok,
                    exit_code=exit_code,
                    stdout=stdout,
                    stderr=stderr,
                    observation=obs_text,
                )
            except Exception:
                continue

        stats = token_stats or {}
        self._db.upsert_token_usage(
            turn_id=turn_id,
            prompt_tokens=stats.get("prompt_tokens"),
            completion_tokens=stats.get("completion_tokens"),
            total_tokens=stats.get("total_tokens"),
            total_cost=stats.get("total_cost"),
        )

        return turn_id

    def list_tool_calls_for_cli(self, *, limit: int = 10) -> str:
        """渲染最近工具调用为 CLI 文本。"""
        rows = self._db.list_recent_tool_calls(limit=limit)
        if not rows:
            return "暂无历史命令记录"
        lines: list[str] = []
        for r in rows:
            created_at = r.get("created_at", "")
            turn_id = r.get("turn_id", "")
            tool_name = r.get("tool_name", "")
            command = r.get("command", "")
            exit_code = r.get("exit_code", "")
            ok = r.get("ok")
            ok_text = "" if ok is None else ("ok" if int(ok) == 1 else "fail")
            lines.append(f"[{created_at}] turn={turn_id} {tool_name} {ok_text} exit={exit_code} :: {command}")
        return "\n".join(lines)

    def add_user_memory(self, *, markdown: str, tags: str) -> int:
        """追加用户永久记忆（markdown + tags）。"""
        return self._db.add_user_memory(markdown=markdown, tags=tags)

    def list_recent_turns_for_cli(self, *, limit: int = 10) -> str:
        """渲染最近对话概要为 CLI 文本。"""
        rows = self._db.list_recent_turns(limit=limit)
        if not rows:
            return "暂无历史对话记录"
        lines: list[str] = []
        for r in rows:
            turn_id = r.get("id", "")
            created_at = r.get("created_at", "")
            user_text = (r.get("user_text") or "").replace("\n", " ")
            lines.append(f"[{created_at}] turn={turn_id} :: {user_text}")
        return "\n".join(lines)

    def list_recent_dialogues_for_cli(self, *, limit: int = 5) -> str:
        if limit <= 0:
            return "暂无历史对话记录"
        rows = self._db.list_recent_turns(limit=limit)
        if not rows:
            return "暂无历史对话记录"
        rows.reverse()

        lines: list[str] = []
        for r in rows:
            turn_id = r.get("id", "")
            created_at = r.get("created_at", "")
            user_text = (r.get("user_text") or "").strip()
            agent_text = (r.get("agent_text") or "").strip()

            lines.append(f"[{created_at}] turn={turn_id}")
            if user_text:
                lines.append("Human: " + user_text.replace("\n", "\n  "))
            if agent_text:
                lines.append("AI: " + agent_text.replace("\n", "\n  "))
            lines.append("")
        if lines and lines[-1] == "":
            lines.pop()
        return "\n".join(lines)
