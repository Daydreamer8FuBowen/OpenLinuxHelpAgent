from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from LinuxAgent.Memory.sqlite_db import SQLiteMemoryDB
from LinuxAgent.log import get_logger


logger = get_logger("Agent.subagents")


def _messages_to_text(messages: Iterable[BaseMessage]) -> str:
    parts: list[str] = []
    for m in messages:
        if isinstance(m, SystemMessage):
            role = "system"
        elif isinstance(m, HumanMessage):
            role = "user"
        elif isinstance(m, AIMessage):
            role = "assistant"
        else:
            role = "message"
        parts.append(f"{role}: {m.content}")
    return "\n".join(parts)


class ContextCompressionAgent:
    def __init__(self, llm: Any) -> None:
        self._llm = llm

    def compress(
        self,
        *,
        messages: list[BaseMessage],
        max_messages: int = 20,
        max_chars: int = 6000,
        keep_last_messages: int = 8,
    ) -> list[BaseMessage]:
        total_chars = sum(len(m.content or "") for m in messages)
        if len(messages) <= max_messages and total_chars <= max_chars:
            return messages

        if keep_last_messages <= 0:
            keep_last_messages = 1

        head = messages[:-keep_last_messages]
        tail = messages[-keep_last_messages:]
        if not head:
            return messages

        logger.info(
            "context compress triggered messages=%s chars=%s keep_last=%s",
            len(messages),
            total_chars,
            keep_last_messages,
        )
        prompt = [
            SystemMessage(
                content=(
                    "你负责压缩对话上下文以便继续对话。\n"
                    "把给定对话压缩为：用户目标、关键约束、已尝试与结果、环境信息、未解决点。\n"
                    "输出为中文纯文本，不要包含多余解释。"
                )
            ),
            HumanMessage(content=_messages_to_text(head)),
        ]
        summary = self._llm.invoke(prompt).content
        summary_message = SystemMessage(content="对话摘要：\n" + (summary or "").strip())
        logger.info("context compress done summary_chars=%s", len(summary_message.content or ""))
        return [summary_message, *tail]


@dataclass(frozen=True)
class ExtractedMemory:
    markdown: str
    tags: str


class MemoryExtractionAgent:
    def __init__(self, llm: Any) -> None:
        self._llm = llm

    def extract(self, *, user_text: str, assistant_text: str) -> ExtractedMemory | None:
        prompt = [
            SystemMessage(
                content=(
                    "你负责从对话中提取“用户永久记忆”。\n"
                    "只提取稳定信息：用户偏好/习惯、环境事实（OS/发行版/版本/路径）、长期目标与约束。\n"
                    "不要提取一次性问题与临时命令输出。\n"
                    "输出严格 JSON："
                    '{"should_write":true|false,"markdown":"...","tags":"tag1,tag2"}'
                )
            ),
            HumanMessage(content=f"用户：{user_text}\n\n助手：{assistant_text}"),
        ]
        raw = self._llm.invoke(prompt).content or ""
        raw = raw.strip()
        try:
            data = json.loads(raw)
        except Exception:
            logger.debug("memory extract parse failed raw=%s", raw[:200])
            return None

        if not isinstance(data, dict) or not data.get("should_write"):
            return None

        markdown = (data.get("markdown") or "").strip()
        tags = (data.get("tags") or "").strip()
        if not markdown:
            return None
        logger.info("memory extracted tags=%s md_chars=%s", tags, len(markdown))
        return ExtractedMemory(markdown=markdown, tags=tags)


class MemoryRetrievalAgent:
    def __init__(self, db: SQLiteMemoryDB) -> None:
        self._db = db

    def build_memory_message(self, *, query: str, limit: int = 5) -> SystemMessage | None:
        rows = self._db.search_user_memories(query=query, limit=limit)
        if not rows:
            return None
        logger.info("memory retrieved matches=%s", len(rows))
        lines: list[str] = []
        for r in rows:
            tags = (r.get("tags") or "").strip()
            md = (r.get("markdown") or "").strip()
            if not md:
                continue
            if tags:
                lines.append(f"- ({tags}) {md}")
            else:
                lines.append(f"- {md}")
        if not lines:
            return None
        return SystemMessage(content="用户永久记忆：\n" + "\n".join(lines))
