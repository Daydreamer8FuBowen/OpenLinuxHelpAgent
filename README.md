# Linux Agent Toolkit（chelp）

面向 Linux 用户的命令行辅助 Agent：支持对话、执行白名单命令、持久化历史与“用户长期记忆”，并可在后续对话中自动召回相关记忆。

## 功能概览

- 命令行入口：`chelp`
- 历史持久化：SQLite（默认 `~/.chelp/memory.db`）
- 历史对话查看：`-h`（默认 5 轮，可指定数量）
- 工具调用记录查看：`-p`（默认 10 条，可指定数量）
- 长期记忆：
  - 对话结束后抽取用户偏好/环境信息等“长期记忆”
  - 新对话开始时按 query 检索并注入到上下文
- 上下文压缩：自动将超长历史压缩为摘要 + 最近对话

## 安装

本项目使用 `pyproject.toml` 打包，并提供控制台脚本入口 `chelp`。

### 开发安装（推荐）

在项目根目录执行：

```bash
pip install -e .
```

优点：源码改动立即生效，适合频繁迭代。

### 普通安装

```bash
pip install .
```

### 命令不可用（Windows 常见）

若出现提示 `chelp.exe ... is not on PATH`，将对应目录加入 PATH（通常类似）：

```
C:\Users\<用户名>\AppData\Roaming\Python\Python311\Scripts
```

## 快速开始

### 查看帮助

注意：本项目将 `-h` 用作“历史对话查看”，因此帮助使用 `--help`。

```bash
chelp --help
```

### 发起一次提问

```bash
chelp 解释一下 top 命令怎么看 CPU
```

### 查看历史对话（区分 Human/AI）

```bash
chelp -h
chelp -h 20
```

输出示例（每轮对话）：

```
[2026-03-11T14:08:04.714821+00:00] turn=2
Human: 查看当前目录
AI: 当前目录是：/workspace
```

### 查看最近工具调用记录

```bash
chelp -p
chelp -p 50
```

### 查看版本与配置

```bash
chelp -v
chelp -V
chelp -c
```

## LLM 配置（llm_config.json）

LLM 配置读取规则：

1. 优先读取“项目根目录”的 `llm_config.json`
2. 若不存在，则读取包内内置配置（随 pip 安装一起分发）

相关实现见 [runtime.py](file:///e:/codes/python/OpenLinuxHelpAgent/OpenLinuxHelpAgent/src/LinuxAgent/App/runtime.py)。

### 推荐用法

- 开发阶段（`pip install -e .`）：直接修改项目根目录的 `llm_config.json`
- 安装成 wheel 后：默认使用包内内置配置；如需改 `base_url/temperature/max_tokens` 等，建议使用源码方式安装（或自行管理包内配置文件）

### 环境变量（部分可覆盖）

- `OPENAI_API_KEY`：当 `llm_config.json` 未提供 `api_key` 时使用
- `OPENAI_MODEL`：当 `llm_config.json` 未提供 `model` 时使用

## 数据与路径

- SQLite 数据库
  - 默认：`~/.chelp/memory.db`
  - 覆盖：`CHELP_SQLITE_DB=/path/to/memory.db`
- 日志
  - 默认（Windows）：`%LOCALAPPDATA%\\chelp\\chelp.log`（或 `%APPDATA%`）
  - 覆盖：`CHELP_LOG_FILE=/path/to/chelp.log`
  - 日志级别：`CHELP_LOG_LEVEL=INFO|DEBUG|...`
  - 是否输出控制台：`CHELP_LOG_CONSOLE=0|1`
- 白名单配置（用于工具执行）
  - 覆盖：`CHELP_WHITELIST_FILE=/path/to/whitelist.json`

## 代码入口

- CLI 参数定义：[cli.py](file:///e:/codes/python/OpenLinuxHelpAgent/OpenLinuxHelpAgent/src/LinuxAgent/App/cli.py)
- 主入口（命令行路由与对话流程）：[Main.py](file:///e:/codes/python/OpenLinuxHelpAgent/OpenLinuxHelpAgent/src/LinuxAgent/App/Main.py)
- SQLite 历史与渲染：[sqlite_history.py](file:///e:/codes/python/OpenLinuxHelpAgent/OpenLinuxHelpAgent/src/LinuxAgent/Memory/sqlite_history.py)
- SQLite 存储层：[sqlite_db.py](file:///e:/codes/python/OpenLinuxHelpAgent/OpenLinuxHelpAgent/src/LinuxAgent/Memory/sqlite_db.py)
