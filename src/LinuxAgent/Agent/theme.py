from __future__ import annotations
"""
Agent 主题入口
职责：
- 统一暴露 Prompt 构造接口，便于后续切换不同主题或模板
"""

from langchain_core.prompts import ChatPromptTemplate

from LinuxAgent.Agent.prompt import build_agent_prompt


def get_prompt(allow_execute: bool) -> ChatPromptTemplate:
    """返回当前主题下的 ChatPromptTemplate。"""
    return build_agent_prompt(allow_execute=allow_execute)
