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


def _project_root():
    from pathlib import Path

    return Path(__file__).resolve().parents[3]


def _load_llm_config() -> dict[str, Any]:
    import json
    from pathlib import Path
    from importlib.resources import files

    path = Path(_project_root()) / "llm_config.json"
    if not path.exists():
        try:
            res = files("LinuxAgent") / "llm_config.json"
            if res.is_file():
                data = json.loads(res.read_text(encoding="utf-8"))
                return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        v = value.strip()
        return v if v else None
    return str(value).strip() or None


def build_llm():
    """构建 LLM（启动时从项目根目录配置文件读取，必要时回退到环境变量）。"""
    import os
    cfg = _load_llm_config()
    model = _string_or_none(cfg.get("model")) or (os.getenv("OPENAI_MODEL") or "gpt-4o-mini")
    provider = _string_or_none(cfg.get("model_provider")) or "openai"
    api_key = _string_or_none(cfg.get("api_key"))
    base_url = _string_or_none(cfg.get("base_url"))
    temperature = cfg.get("temperature")
    timeout = cfg.get("timeout")
    max_tokens = cfg.get("max_tokens")

    if api_key is None:
        api_key = os.getenv("OPENAI_API_KEY") or None

    if base_url is not None:
        base_url = base_url.strip().strip('"').strip("'")

    if temperature is None:
        temperature = 0

    try:
        from langchain.chat_models import init_chat_model

        kwargs: dict[str, Any] = {}
        if api_key is not None:
            kwargs["api_key"] = api_key
        if base_url is not None:
            kwargs["base_url"] = base_url
        if timeout is not None:
            kwargs["timeout"] = timeout
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        kwargs["temperature"] = temperature

        return init_chat_model(
            model=model,
            model_provider=provider,
            **kwargs,
        )
    except Exception:
        init_kwargs: dict[str, Any] = {"model": model, "temperature": temperature}
        if api_key is not None:
            init_kwargs["api_key"] = api_key
        if base_url is not None:
            init_kwargs["base_url"] = base_url
        if timeout is not None:
            init_kwargs["timeout"] = timeout
        if max_tokens is not None:
            init_kwargs["max_tokens"] = max_tokens
        return ChatOpenAI(**init_kwargs)

def build_executor(allow_execute: bool, extra_whitelist: set[str] | None = None, sandbox: Any | None = None) -> Any:
    """按执行权限装配工具与系统提示词，返回可 invoke 的 Agent。"""
    llm = build_llm()
    tools = create_tools(allow_execute, extra_whitelist, sandbox)
    system_prompt = build_system_prompt(allow_execute=allow_execute)
    try:
        from langgraph.checkpoint.memory import InMemorySaver
        checkpointer = InMemorySaver()
        return create_agent(model=llm, tools=tools, system_prompt=system_prompt, checkpointer=checkpointer)
    except Exception:
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
