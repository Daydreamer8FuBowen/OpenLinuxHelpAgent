from __future__ import annotations
"""
应用层运行时
职责：
- 组装 LLM 与工具，生成 LangChain v1 Agent
- 提供执行一次查询的封装，返回输出、工具步骤与可选 token 统计
"""

from dataclasses import dataclass
from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_openai import ChatOpenAI

from LinuxAgent.Agent.prompt import build_system_prompt
from LinuxAgent.Agent.tools import create_tools
from LinuxAgent.log import get_logger


logger = get_logger("App.runtime")


@dataclass(frozen=True)
class _ToolAction:
    tool: str
    tool_input: Any



def build_llm():
    """构建 LLM（默认从环境读取模型名）。"""
    import os

    return ChatOpenAI(model=os.getenv("OPENAI_MODEL") or "gpt-4o-mini", temperature=0)

def build_executor(allow_execute: bool, extra_whitelist: set[str] | None = None, sandbox: Any | None = None) -> Any:
    """按执行权限装配工具与系统提示词，返回可 invoke 的 Agent。"""
    llm = build_llm()
    tools = create_tools(allow_execute, extra_whitelist, sandbox)
    system_prompt = build_system_prompt(allow_execute=allow_execute)
    return create_agent(model=llm, tools=tools, system_prompt=system_prompt)


def _extract_output_text(result: Any) -> str:
    if isinstance(result, dict):
        messages = result.get("messages")
        if isinstance(messages, list):
            for m in reversed(messages):
                if isinstance(m, AIMessage) and (m.content or "").strip():
                    return (m.content or "").strip()
        output = result.get("output")
        if isinstance(output, str):
            return output.strip()
    if isinstance(result, AIMessage):
        return (result.content or "").strip()
    return ""


def _extract_tool_steps(result: Any) -> list[tuple[Any, Any]]:
    if not isinstance(result, dict):
        return []
    messages = result.get("messages")
    if not isinstance(messages, list):
        return []

    tool_call_by_id: dict[str, dict[str, Any]] = {}
    steps: list[tuple[Any, Any]] = []
    for m in messages:
        if isinstance(m, AIMessage) and getattr(m, "tool_calls", None):
            for call in m.tool_calls:
                if isinstance(call, dict):
                    call_id = call.get("id")
                    name = call.get("name")
                    args = call.get("args")
                else:
                    call_id = getattr(call, "id", None)
                    name = getattr(call, "name", None)
                    args = getattr(call, "args", None)
                if call_id:
                    tool_call_by_id[str(call_id)] = {"name": name, "args": args}
        elif isinstance(m, ToolMessage):
            call_id = str(getattr(m, "tool_call_id", "") or "")
            call = tool_call_by_id.get(call_id, {})
            tool_name = call.get("name") or getattr(m, "name", None) or "tool"
            tool_input = call.get("args") or {}
            steps.append((_ToolAction(tool=str(tool_name), tool_input=tool_input), m.content))
    return steps


def run_query(executor: Any, *, user_text: str, chat_history: list[Any], capture_tokens: bool):
    """执行一次查询；当 capture_tokens=True 时统计并返回 token 消耗。"""
    token_stats = None
    callback_cm = None
    if capture_tokens:
        try:
            from langchain_community.callbacks import get_openai_callback

            callback_cm = get_openai_callback()
        except Exception:
            callback_cm = None

    messages: list[BaseMessage] = [m for m in chat_history if isinstance(m, BaseMessage)]
    messages.append(HumanMessage(content=user_text))

    if callback_cm is not None:
        with callback_cm as cb:
            result = executor.invoke({"messages": messages})
            token_stats = {
                "total_tokens": cb.total_tokens,
                "prompt_tokens": cb.prompt_tokens,
                "completion_tokens": cb.completion_tokens,
                "total_cost": getattr(cb, "total_cost", None),
            }
    else:
        result = executor.invoke({"messages": messages})

    output_text = _extract_output_text(result)
    tool_steps = _extract_tool_steps(result)
    return output_text, tool_steps, token_stats
