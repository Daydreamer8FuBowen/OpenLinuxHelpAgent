from __future__ import annotations
"""
Agent 工具集合
职责：
- 提供可被 LangChain 调用的 bash 工具（带白名单与拒绝前缀）
- 解析 Agent 中间步骤为结构化事件，用于持久化与审计
"""

import os
import shlex
import shutil
import subprocess
from typing import Any, Callable, Iterable

from langchain_core.tools import tool
from LinuxAgent.log import get_logger


logger = get_logger("Agent.tools")


def _first_token(command: str) -> str:
    """提取命令首个 token，用于白名单/黑名单判断。"""
    try:
        parts = shlex.split(command, posix=(os.name != "nt"))
        return parts[0] if parts else ""
    except Exception:
        return command.strip().split(" ", 1)[0]


def _create_runner(
    allow_execute: bool,
    extra_whitelist: set[str] | None = None,
    sandbox: Any | None = None,
    whitelist_adder: Callable[[str], None] | None = None,
):
    """根据执行权限创建命令运行器，封装白名单与拒绝前缀校验。"""
    readonly_allowlist = {
        "ls",
        "pwd",
        "whoami",
        "id",
        "uname",
        "date",
        "uptime",
        "df",
        "du",
        "free",
        "ps",
        "top",
        "env",
        "printenv",
        "echo",
        "cat",
        "head",
        "tail",
        "less",
        "more",
        "grep",
        "egrep",
        "fgrep",
        "sed",
        "awk",
        "cut",
        "sort",
        "uniq",
        "wc",
        "find",
        "which",
        "whereis",
        "stat",
        "ip",
        "ss",
        "netstat",
        "curl",
        "wget",
        "ping",
        "traceroute",
        "dig",
        "nslookup",
        "systemctl",
        "journalctl",
        "dmesg",
    }
    blocked_prefixes = {
        "rm",
        "sudo",
        "su",
        "dd",
        "mkfs",
        "fdisk",
        "parted",
        "truncate",
        "chmod",
        "chown",
        "useradd",
        "usermod",
        "groupadd",
        "groupmod",
        "passwd",
        "shutdown",
        "reboot",
        "poweroff",
        "kill",
        "killall",
        "pkill",
        "tee",
    }

    # 合并外部白名单（若提供），忽略在黑名单中的命令
    external = {(_first_token(c)) for c in (extra_whitelist or set())}
    external = {c for c in external if c and c not in blocked_prefixes}
    effective_allowlist = set(readonly_allowlist) | set(external)
    logger.debug("tool allowlist size=%s external=%s", len(effective_allowlist), len(external))

    def run_command(command: str) -> dict[str, Any]:
        """执行命令并返回结构化结果（ok/exit_code/stdout/stderr）。"""
        if not allow_execute:
            logger.info("command denied (execution disabled) cmd=%s", command[:200])
            return {
                "ok": False,
                "exit_code": None,
                "stdout": "",
                "stderr": "执行已禁用（未传 -y）。这是一条建议命令，不会在本机运行。",
            }
        first = _first_token(command)
        if not first:
            logger.info("command denied (empty)")
            return {"ok": False, "exit_code": None, "stdout": "", "stderr": "空命令"}
        if first in blocked_prefixes:
            logger.warning("command denied (blocked) token=%s cmd=%s", first, command[:200])
            return {
                "ok": False,
                "exit_code": None,
                "stdout": "",
                "stderr": f"命令被拒绝：{first} 可能具有破坏性或需要更高权限",
            }
        if first not in effective_allowlist:
            try:
                from langgraph.types import interrupt

                approved = interrupt(
                    {
                        "tool": "bash",
                        "command": command,
                        "description": f"命令不在白名单内，是否允许并加入白名单：{first}",
                    }
                )
            except Exception:
                approved = False
            if approved:
                effective_allowlist.add(first)
                if whitelist_adder is not None:
                    try:
                        whitelist_adder(first)
                    except Exception:
                        logger.exception("whitelist add failed token=%s", first)
                logger.info("command allow (added whitelist) token=%s cmd=%s", first, command[:200])
            else:
                logger.info("command denied (not whitelisted) token=%s cmd=%s", first, command[:200])
                return {
                    "ok": False,
                    "exit_code": None,
                    "stdout": "",
                    "stderr": f"命令不在白名单内：{first}",
                }
        try:
            logger.info("command run token=%s cmd=%s", first, command[:200])
            if sandbox is not None:
                exit_code, stdout, stderr = sandbox.exec(command=command)
                return {
                    "ok": exit_code == 0,
                    "exit_code": exit_code,
                    "stdout": stdout or "",
                    "stderr": stderr or "",
                }
            if shutil.which("bash"):
                proc = subprocess.run(
                    ["bash", "-lc", command],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
            else:
                proc = subprocess.run(
                    command,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
            return {
                "ok": proc.returncode == 0,
                "exit_code": proc.returncode,
                "stdout": proc.stdout or "",
                "stderr": proc.stderr or "",
            }
        except subprocess.TimeoutExpired:
            logger.warning("command timeout token=%s cmd=%s", first, command[:200])
            return {
                "ok": False,
                "exit_code": None,
                "stdout": "",
                "stderr": "命令执行超时（30s）",
            }
        except Exception as e:
            logger.exception("command failed token=%s cmd=%s", first, command[:200])
            return {
                "ok": False,
                "exit_code": None,
                "stdout": "",
                "stderr": f"命令执行失败：{type(e).__name__}: {e}",
            }

    return run_command


def create_tools(
    allow_execute: bool,
    extra_whitelist: set[str] | None = None,
    sandbox: Any | None = None,
    whitelist_adder: Callable[[str], None] | None = None,
):
    """创建并返回 LangChain 工具列表（当前仅包含 bash）。"""
    runner = _create_runner(allow_execute, extra_whitelist, sandbox, whitelist_adder)

    @tool("bash")
    def bash_tool(command: str, dangerous: bool | None = None, description: str | None = None) -> str:
        """执行 bash 命令；当标记为风险指令（dangerous=True）时触发人工确认；未授权执行时返回“执行已禁用”的说明文本。"""
        try:
            if dangerous:
                from langgraph.types import interrupt
                approved = interrupt({"tool": "bash", "command": command, "description": description or ""})
                if not approved:
                    return "\n".join(["exit_code=None", "stderr:", "用户拒绝执行危险指令"])
        except Exception:
            pass
        result = runner(command)
        stdout = (result.get("stdout") or "").strip()
        stderr = (result.get("stderr") or "").strip()
        exit_code = result.get("exit_code")
        parts = [f"exit_code={exit_code}"]
        if stdout:
            parts.append("stdout:\n" + stdout[:6000])
        if stderr:
            parts.append("stderr:\n" + stderr[:6000])
        return "\n".join(parts)

    return [bash_tool]


def parse_tool_events(intermediate_steps: Iterable[Any]) -> list[dict[str, Any]]:
    """解析 Agent 的 intermediate_steps，提取工具名、输入与退出码。"""
    events: list[dict[str, Any]] = []
    for step in intermediate_steps or []:
        try:
            action, observation = step
            tool_name = getattr(action, "tool", None) or "tool"
            tool_input = getattr(action, "tool_input", None)
            if isinstance(tool_input, dict):
                command = tool_input.get("command") or tool_input.get("input") or str(tool_input)
            else:
                command = str(tool_input) if tool_input is not None else ""
            exit_code = None
            if isinstance(observation, str) and observation.startswith("exit_code="):
                first_line = observation.splitlines()[0]
                _, _, code_str = first_line.partition("=")
                try:
                    exit_code = int(code_str)
                except Exception:
                    exit_code = None
            events.append({"tool": tool_name, "command": command, "exit_code": exit_code})
        except Exception:
            continue
    return events
