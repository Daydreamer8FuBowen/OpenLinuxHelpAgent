from __future__ import annotations
"""
记忆装载抽象
职责：
- 提供统一接口，用于装载聊天历史与相关记忆
- 通过不同实现类，支持切换/组合不同的记忆装载策略
"""

from abc import ABC, abstractmethod
from typing import List, Optional

from langchain_core.messages import BaseMessage, SystemMessage

from LinuxAgent.Agent.subagents import MemoryRetrievalAgent
from LinuxAgent.Memory.sqlite_db import SQLiteMemoryDB
from LinuxAgent.Memory.sqlite_history import SqliteHistory
from LinuxAgent.log import get_logger

logger = get_logger("Memory.loader")


class MemoryLoader(ABC):
    """记忆装载器抽象基类。"""

    @abstractmethod
    def load(self) -> List[BaseMessage]:
        """按当前策略装载消息列表。"""
        pass


class ChatHistoryLoader(MemoryLoader):
    """装载最近聊天历史消息。"""

    def __init__(self, history: SqliteHistory, limit_messages: int = 20):
        self._history = history
        self._limit_messages = limit_messages

    def load(self) -> List[BaseMessage]:
        messages = self._history.load_chat_history_messages(limit_messages=self._limit_messages)
        logger.info("ChatHistoryLoader loaded messages=%s", len(messages))
        return messages


class RetrievalMemoryLoader(MemoryLoader):
    """按查询检索并注入相关的用户长期记忆。"""

    def __init__(self, db: SQLiteMemoryDB, query: str, limit: int = 5):
        self._db = db
        self._query = query
        self._limit = limit
        self._retriever = MemoryRetrievalAgent(db)

    def load(self) -> List[BaseMessage]:
        memory_message = self._retriever.build_memory_message(query=self._query, limit=self._limit)
        if memory_message:
            logger.info("RetrievalMemoryLoader retrieved memory")
            return [memory_message]
        return []
