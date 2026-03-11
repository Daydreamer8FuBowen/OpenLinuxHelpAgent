from __future__ import annotations
"""
Agent 层 Prompt 与历史读写
职责：
- 构建 System Prompt 与 ChatPromptTemplate（含聊天历史与工具 scratchpad）
- 管理历史消息与工具事件的 JSONL 持久化（轻量级，便于快速启动）
"""

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder


def build_system_prompt(*, allow_execute: bool) -> str:
    """根据执行权限开关生成系统提示词，约束工具使用与输出风格。"""
    execute_policy = (
        "你可以调用 bash 工具执行命令，每次只执行一条命令。"
        if allow_execute
        else "你不能执行任何命令。你可以调用 bash 工具获取“执行已禁用”的提示，并给出建议命令。"
    )
    return "\n".join(
        [
            "你是一个面向 Linux 用户的命令行助手。你的目标是用最少的步骤帮助用户完成问题定位与命令建议。",
            execute_policy,
            "你不能捏造命令输出；如果需要系统信息，请通过 bash 工具获取。",
            "当给出命令时，优先给出可复制的完整命令；不要包含多余解释性前缀。",
            "默认假设用户权限为普通用户；涉及 root/危险操作必须显式提醒并给出只读替代方案。",
        ]
    )


def build_agent_prompt(*, allow_execute: bool) -> ChatPromptTemplate:
    """组合系统提示词、历史消息占位与人类输入，供 Agent 使用。"""
    return ChatPromptTemplate.from_messages(
        [
            ("system", build_system_prompt(allow_execute=allow_execute)),
            MessagesPlaceholder("chat_history"),
            ("human", "{input}"),
            MessagesPlaceholder("agent_scratchpad"),
        ]
    )


def _utc_now_iso() -> str:
    """UTC 时间戳（ISO 8601），用于持久化记录。"""
    return datetime.now(tz=timezone.utc).isoformat()


def _default_history_file() -> Path:
    """历史 JSONL 文件路径，支持 CHELP_HISTORY_FILE 环境变量覆盖。"""
    configured = os.getenv("CHELP_HISTORY_FILE")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".chelp" / "history.jsonl"


@dataclass(frozen=True)
class HistoryPaths:
    history_file: Path
    """历史持久化路径集合（当前仅包含 JSONL 文件）。"""

    @staticmethod
    def load() -> "HistoryPaths":
        """加载默认路径配置。"""
        return HistoryPaths(history_file=_default_history_file())

    def ensure_dirs(self) -> None:
        """确保历史目录存在。"""
        self.history_file.parent.mkdir(parents=True, exist_ok=True)


def load_chat_history_messages(*, limit_messages: int = 20) -> list[BaseMessage]:
    """读取最近 N 条 user/assistant 消息，转换为 LangChain 消息对象。"""
    paths = HistoryPaths.load()
    if not paths.history_file.exists():
        return []

    messages: list[BaseMessage] = []
    try:
        for line in paths.history_file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            if record.get("type") != "message":
                continue
            role = record.get("role")
            content = record.get("content", "")
            if role == "user":
                messages.append(HumanMessage(content=content))
            elif role == "assistant":
                messages.append(AIMessage(content=content))
    except Exception:
        return []

    if limit_messages <= 0:
        return []
    return messages[-limit_messages:]


def append_chat_turn(
    *,
    user_text: str,
    assistant_text: str,
    tool_events: list[dict[str, Any]] | None = None,
) -> None:
    """将一轮对话与工具事件以 JSONL 形式追加写入。"""
    paths = HistoryPaths.load()
    paths.ensure_dirs()

    records: list[dict[str, Any]] = [
        {"type": "message", "ts": _utc_now_iso(), "role": "user", "content": user_text},
        {
            "type": "message",
            "ts": _utc_now_iso(),
            "role": "assistant",
            "content": assistant_text,
        },
    ]

    for event in tool_events or []:
        records.append({"type": "tool", "ts": _utc_now_iso(), **event})

    with paths.history_file.open("a", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def load_tool_events(*, limit: int = 10) -> list[dict[str, Any]]:
    """读取最近 N 条工具事件记录。"""
    paths = HistoryPaths.load()
    if not paths.history_file.exists():
        return []

    events: list[dict[str, Any]] = []
    try:
        for line in paths.history_file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            if record.get("type") == "tool":
                events.append(record)
    except Exception:
        return []

    if limit <= 0:
        return []
    return events[-limit:]


def render_tool_events_for_cli(events: list[dict[str, Any]]) -> str:
    """将工具事件渲染为简洁的 CLI 文本。"""
    if not events:
        return "暂无历史命令记录"

    lines: list[str] = []
    for e in events:
        ts = e.get("ts", "")
        tool_name = e.get("tool", "")
        command = e.get("command", "")
        exit_code = e.get("exit_code", "")
        lines.append(f"[{ts}] {tool_name} exit={exit_code} :: {command}")
    return "\n".join(lines)

