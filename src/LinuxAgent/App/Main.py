#!/usr/bin/env python3
"""
应用入口
职责：
- 解析 CLI 参数，打印版本与配置
- 组织一次对话流程：读取历史 → 执行 → 输出结果 → 写入数据库 → 打印 token
"""
import os
from LinuxAgent import __version__

from LinuxAgent.App.cli import build_parser, parse_args
from LinuxAgent.App.runtime import build_executor, build_llm, run_query
from LinuxAgent.Agent.subagents import ContextCompressionAgent, MemoryExtractionAgent
from LinuxAgent.App.config import load_whitelist
from LinuxAgent.Memory.loader import ChatHistoryLoader, RetrievalMemoryLoader
from LinuxAgent.Memory.sqlite_db import SqlitePaths
from LinuxAgent.Memory.sqlite_history import SqliteHistory
from LinuxAgent.log import get_logger, init_logging
from LinuxAgent.App.docker_sandbox import DockerSandbox


logger = get_logger("App.Main")
TEST_MODE = False
SANDBOX: DockerSandbox | None = None


def main():
    """命令行入口：负责路由与执行流程控制。"""
    init_logging()
    args = parse_args()
    logger.info("start version=%s", __version__)

    if args.v:
        print(__version__)
        return

    if args.V:
        print(f"LinuxAgent {__version__}")
        paths = SqlitePaths.load()
        print(f"DB: {paths.db_file}")
        logger.info("print version detail db=%s", paths.db_file)
        return

    if args.c:
        paths = SqlitePaths.load()
        print(f"DB: {paths.db_file}")
        print(f"AllowExecute: {bool(args.y)}")
        print(f"Model: {os.getenv('OPENAI_MODEL', '')}")
        logger.info("print config db=%s allow_execute=%s", paths.db_file, bool(args.y))
        return

    history = SqliteHistory()  # 初始化 SQLite 历史管理器
    logger.info("history db=%s", history.db.db_file)

    if args.h is not None:
        logger.info("print history dialogues limit=%s", args.h)
        print(history.list_recent_dialogues_for_cli(limit=args.h))
        return

    if args.p is not None:
        logger.info("print tool calls limit=%s", args.p)
        print(history.list_tool_calls_for_cli(limit=args.p))
        return

    allow_execute = bool(args.y)  # 是否允许实际执行白名单命令
    extra_whitelist = load_whitelist()
    logger.info("whitelist loaded size=%s", len(extra_whitelist))
    sandbox = None
    global TEST_MODE, SANDBOX
    TEST_MODE = bool(args.test)
    if TEST_MODE:
        SANDBOX = DockerSandbox()
        try:
            SANDBOX.ensure_started()
            sandbox = SANDBOX
            logger.info("test mode enabled image=%s", SANDBOX.image)
        except Exception:
            logger.exception("test mode init failed")

    user_text = " ".join(args.text or []).strip()  # 合并剩余参数作为输入文本
    if not user_text:
        build_parser().print_help()
        return

    try:
        executor = build_executor(allow_execute, extra_whitelist, sandbox)  # 构建 Agent 执行器

        # 1. 加载最近历史消息
        history_loader = ChatHistoryLoader(history, limit_messages=20)
        chat_history = history_loader.load()

        # 2. 检索并注入相关记忆
        retrieval_loader = RetrievalMemoryLoader(history.db, query=user_text, limit=5)
        injected_memories = retrieval_loader.load()
        if injected_memories:
            chat_history = injected_memories + chat_history

        compressor = ContextCompressionAgent(build_llm())
        chat_history = compressor.compress(messages=chat_history, max_messages=20, max_chars=6000, keep_last_messages=8)
        logger.info("context ready messages=%s", len(chat_history))

        from langchain_core.messages import BaseMessage, HumanMessage
        try:
            from langgraph.types import Command
        except Exception:
            Command = None

        messages: list[BaseMessage] = [m for m in chat_history if isinstance(m, BaseMessage)]
        messages.append(HumanMessage(content=user_text))

        username = os.getenv("USERNAME") or os.getenv("USER") or ""
        if not username:
            try:
                import getpass
                username = getpass.getuser()
            except Exception:
                username = "unknown"
        thread_id = f"chelp-{username}-{os.getpid()}"
        config = {"configurable": {"thread_id": thread_id, "user_id": username}}

        result = executor.invoke({"messages": messages}, config=config, version="v2")
        while True:
            interrupts = getattr(result, "interrupts", None)
            if not interrupts and isinstance(result, dict):
                interrupts = result.get("__interrupt__")
            if not interrupts:
                break
            payload = None
            try:
                payload = interrupts[0].value
            except Exception:
                try:
                    payload = interrupts[0].get("value")
                except Exception:
                    payload = None
            if isinstance(payload, dict):
                desc = payload.get("description") or ""
                cmd = payload.get("command") or ""
                print("危险指令待确认：")
                if desc:
                    print(desc)
                if cmd:
                    print(cmd)
            else:
                print("有待确认的操作")
                if payload:
                    print(str(payload))
            decision = input("是否执行? [Y/n]: ").strip().lower()
            approved = decision not in ("n", "no")
            if Command is not None:
                result = executor.invoke(Command(resume=approved), config=config, version="v2")
            else:
                result = executor.invoke({"resume": approved}, config=config)

        from LinuxAgent.App.runtime import _extract_output_text, _extract_tool_steps
        output_text = _extract_output_text(result)
        intermediate_steps = _extract_tool_steps(result)
        token_stats = None
        print(output_text)
        logger.info("agent done tools=%s token_stats=%s", len(intermediate_steps or []), bool(token_stats))

        history.save_turn(
            user_text=user_text,
            assistant_text=output_text,
            tool_steps=intermediate_steps,
            token_stats=token_stats,
            model=os.getenv("OPENAI_MODEL") or "gpt-4o-mini",
            allow_execute=allow_execute,
        )
        logger.info("turn saved")

        extractor = MemoryExtractionAgent(build_llm())
        extracted = extractor.extract(user_text=user_text, assistant_text=output_text)
        if extracted is not None:
            history.add_user_memory(markdown=extracted.markdown, tags=extracted.tags)
            logger.info("user memory added tags=%s", extracted.tags)

        if token_stats:
            print("\nToken:")
            for k, v in token_stats.items():
                if v is not None:
                    print(f"{k}={v}")
    finally:
        if SANDBOX is not None:
            SANDBOX.close()
            SANDBOX = None


if __name__ == "__main__":
    main()
